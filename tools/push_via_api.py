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


def api_request(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    """调用 GitHub API。"""
    url = API + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "dsh-push-script")
    if data is not None:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"message": raw}


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


def get_remote_sha(token: str, rel_path: str) -> str | None:
    """取远端某个文件的当前 sha（更新已存在的文件时必须提供）。"""
    # 路径里的特殊字符要转义
    from urllib.parse import quote

    status, data = api_request("GET", f"/repos/{OWNER}/{REPO}/contents/{quote(rel_path)}?ref={BRANCH}", token)
    if status == 200:
        return data.get("sha")
    return None


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
    skipped = 0
    failed: list[str] = []

    for path in files:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        content = path.read_bytes()
        encoded = base64.b64encode(content).decode("ascii")

        remote_sha = get_remote_sha(token, rel)

        # 内容没变就不推（省请求配额）
        if remote_sha:
            status, data = api_request("GET", f"/repos/{OWNER}/{REPO}/contents/{rel}?ref={BRANCH}", token)
            # 无法直接比对内容（API 只给 sha，是 git blob 的 sha），所以一律推送

        body: dict = {"message": message, "content": encoded, "branch": BRANCH}
        if remote_sha:
            body["sha"] = remote_sha

        status, data = api_request("PUT", f"/repos/{OWNER}/{REPO}/contents/{rel}", token, body)

        if status in (200, 201):
            pushed += 1
            print(f"  OK   {rel}")
        else:
            skipped += 1
            failed.append(f"{rel}: HTTP {status} {data.get('message', '')}")
            print(f"  FAIL {rel}: HTTP {status} {data.get('message', '')[:80]}")

    print()
    print(f"成功 {pushed} 个，失败 {skipped} 个")
    if failed:
        print("失败明细：")
        for item in failed:
            print("  " + item)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
