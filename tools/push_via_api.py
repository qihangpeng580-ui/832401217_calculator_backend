# 通过 GitHub Contents API 推送整个仓库
#
# 为什么需要这个脚本：
#   本机的 git push 走不通 —— github.com:443 能建立 TCP 连接，
#   但 TLS 握手后被服务端重置（`curl 52 Empty reply from server`），
#   走本地代理（127.0.0.1:7897）也一样。
#   而 api.github.com 是通的，所以改用 Contents API 逐个文件上传。
#
# 用法：
#   py -3.12 tools/push_via_api.py                   推送所有改动
#   py -3.12 tools/push_via_api.py --dry-run         只看会推什么
#   py -3.12 tools/push_via_api.py --message "..."   指定提交信息
#
# 令牌读取顺序：
#   1. 环境变量 GITHUB_TOKEN
#   2. ~/.git-credentials 里 github.com 那一行
# 令牌不会被打印出来。

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OWNER = "qihangpeng580-ui"
REPO = PROJECT_ROOT.name
BRANCH = "main"
API = "https://api.github.com"

# 不推送的文件（本地产物）
SKIP_DIRS = {".git", "__pycache__", ".vscode", "data", "venv", ".venv"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".db", ".log"}


def find_token() -> str:
    """找到 GitHub 令牌。"""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token.strip()

    cred_file = Path.home() / ".git-credentials"
    if cred_file.exists():
        for line in cred_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if "github.com" not in line:
                continue
            # 形如 https://user:token@github.com
            _, _, rest = line.partition("://")
            userinfo, _, _ = rest.partition("@")
            _, _, secret = userinfo.partition(":")
            if secret:
                return secret.strip()

    raise SystemExit("找不到 GitHub 令牌：请设置环境变量 GITHUB_TOKEN，或确认 ~/.git-credentials 里有 github.com 条目")


def api_request(
    method: str,
    path: str,
    token: str,
    body: dict | None = None,
    retries: int = 4,
) -> tuple[int, dict]:
    """调用 GitHub API，带重试。

    ★ 为什么要重试：
       本机网络在推送到一半时出现过 RemoteDisconnected（连接被切断）。
       这是网络层的问题，不是请求本身有问题 —— 重试通常就能成功。
       没有重试的脚本推到第 20 个文件断掉，前面 19 个要重推一遍，很浪费时间。
    """
    import time

    url = API + path
    data = json.dumps(body).encode("utf-8") if body is not None else None

    last_error: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"token {token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "dsh-push-script")
        if data is not None:
            req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            # 5xx 是服务端临时问题，值得重试；4xx 是请求本身的问题，重试没用
            if exc.code >= 500 and attempt < retries - 1:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
                continue
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"message": raw}
        except Exception as exc:  # noqa: BLE001 - 连接层错误也重试
            last_error = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise

    raise last_error if last_error else RuntimeError("请求失败且没有记录到异常")


def collect_files() -> list[Path]:
    """列出要推送的文件。"""
    files: list[Path] = []
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(PROJECT_ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        files.append(path)
    return files


def get_remote_state(token: str, rel_path: str) -> tuple[str | None, bytes | None]:
    """取远端文件的 (sha, 内容)。

    为什么连内容一起取：
        网络中断后重跑脚本时，如果只比对 sha 是没法判断"本地和远端是否一致"的
        （远端 sha 是 git blob 的哈希，本地算不出来除非自己实现 git 的哈希算法）。
        直接取回内容比对，才能跳过没变的文件，实现真正的断点续传。
        代价是多一次请求，但比重复上传整个文件便宜。
    """
    from urllib.parse import quote

    status, data = api_request(
        "GET", f"/repos/{OWNER}/{REPO}/contents/{quote(rel_path, safe='/')}?ref={BRANCH}", token
    )
    if status != 200:
        return None, None

    sha = data.get("sha")
    encoded = data.get("content")
    if not encoded:
        return sha, None

    try:
        # GitHub 返回的 base64 里带换行，要去掉
        return sha, base64.b64decode(encoded.replace("\n", ""))
    except Exception:  # noqa: BLE001
        return sha, None


def main() -> int:
    parser = argparse.ArgumentParser(description="通过 GitHub Contents API 推送仓库")
    parser.add_argument("--dry-run", action="store_true", help="只列出将要推送的文件")
    parser.add_argument("--message", default="", help="提交信息")
    args = parser.parse_args()

    token = find_token()
    files = collect_files()

    print(f"仓库：{OWNER}/{REPO}    分支：{BRANCH}")
    print(f"待推送文件：{len(files)} 个")

    if args.dry_run:
        for path in files:
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            print(f"  {rel}  ({path.stat().st_size} 字节)")
        return 0

    message = args.message or "chore: 通过 API 同步文件"

    pushed = 0
    unchanged = 0
    failed: list[str] = []

    for path in files:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        content = path.read_bytes()

        remote_sha, remote_content = get_remote_state(token, rel)

        # 内容一致就跳过 —— 断点续传靠的就是这一句。
        # 换行符差异会导致误判为"有变化"，那就多推一次，不影响正确性。
        if remote_sha and remote_content is not None and remote_content == content:
            unchanged += 1
            print(f"  --   {rel}（远端已是最新，跳过）")
            continue

        encoded = base64.b64encode(content).decode("ascii")
        body: dict = {"message": message, "content": encoded, "branch": BRANCH}
        if remote_sha:
            body["sha"] = remote_sha

        # ★ 路径必须 URL 编码后再拼进 URL。
        #   仓库里有中文文件名（如「你要实现的部分.md」），
        #   直接把中文放进 URL 会抛 UnicodeEncodeError: 'ascii' codec can't encode ...
        #   因为 Python 的 http.client 拼请求行时强制要求 ascii。
        #   safe="/" 让路径分隔符保持原样。
        from urllib.parse import quote

        encoded_path = quote(rel, safe="/")

        status, data = api_request("PUT", f"/repos/{OWNER}/{REPO}/contents/{encoded_path}", token, body)

        if status in (200, 201):
            pushed += 1
            print(f"  OK   {rel}")
        else:
            failed.append(f"{rel}: HTTP {status} {data.get('message', '')}")
            print(f"  FAIL {rel}: HTTP {status} {data.get('message', '')[:80]}")

    print()
    print(f"新推送 {pushed} 个，跳过 {unchanged} 个，失败 {len(failed)} 个")
    if failed:
        print("失败明细：")
        for item in failed:
            print("  " + item)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
