# Push the whole repository through the GitHub Contents API
#
# Why this script is needed:
#   git push from this machine does not work -- github.com:443 accepts the TCP connection,
#   but the server resets it after the TLS handshake (`curl 52 Empty reply from server`),
#   and going through the local proxy (127.0.0.1:7897) behaves the same.
#   api.github.com does work, so files are uploaded one by one through the Contents API.
#
# Usage:
#   py -3.12 tools/push_via_api.py                   push all changes
#   py -3.12 tools/push_via_api.py --dry-run         only list what would be pushed
#   py -3.12 tools/push_via_api.py --message "..."   set the commit message
#
# Token lookup order:
#   1. the GITHUB_TOKEN environment variable
#   2. the github.com line in ~/.git-credentials
# The token is never printed.

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

# files not pushed (local artifacts)
SKIP_DIRS = {".git", "__pycache__", ".vscode", "data", "venv", ".venv"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".db", ".log"}


def find_token() -> str:
    """Find the GitHub token."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token.strip()

    cred_file = Path.home() / ".git-credentials"
    if cred_file.exists():
        for line in cred_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if "github.com" not in line:
                continue
            # shaped like https://user:token@github.com
            _, _, rest = line.partition("://")
            userinfo, _, _ = rest.partition("@")
            _, _, secret = userinfo.partition(":")
            if secret:
                return secret.strip()

    raise SystemExit(
        "GitHub token not found: set the GITHUB_TOKEN environment variable, "
        "or make sure ~/.git-credentials has a github.com entry"
    )


def api_request(
    method: str,
    path: str,
    token: str,
    body: dict | None = None,
    retries: int = 4,
) -> tuple[int, dict]:
    """Call the GitHub API, with retries.

    Why the retries:
       the network here has dropped mid-push with RemoteDisconnected (connection cut),
       which is a network-layer problem, not a bad request, and a retry usually works.
       Without retries, a push that dies at file 20 has to redo the previous 19.
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
            # 5xx is a temporary server-side problem worth retrying;
            # 4xx is a bad request, retrying is useless
            if exc.code >= 500 and attempt < retries - 1:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
                continue
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"message": raw}
        except Exception as exc:  # noqa: BLE001 - connection-layer errors are retried too
            last_error = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise

    raise last_error if last_error else RuntimeError("request failed and no exception was recorded")


def collect_files() -> list[Path]:
    """List the files to push."""
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
    """Fetch the remote file's (sha, content).

    Why the content comes along:
        when the script is rerun after a network drop, comparing sha alone cannot tell
        whether local and remote match (the remote sha is a git blob hash that cannot be
        computed locally). Fetching the content and comparing it is what lets unchanged
        files be skipped, giving a real resumable push for one extra cheap request.
    """
    from urllib.parse import quote

    status, data = api_request(
        "GET", f"/repos/{OWNER}/{REPO}/contents/{quote(rel_path, safe='/')}?ref={BRANCH}", token
    )
    if status != 200:
        return None, None

    sha = data.get("sha")
    encoded = data.get("content")
    # `is None` is required here, not `not encoded`:
    #   an empty file (such as each __init__.py) returns content "", and "" is falsy,
    #   so `not encoded` would mistake it for "no content available" and re-upload it
    #   on every push, creating a pile of commits with the same title.
    if encoded is None:
        return sha, None

    try:
        # the base64 GitHub returns contains newlines, strip them
        return sha, base64.b64decode(encoded.replace("\n", ""))
    except Exception:  # noqa: BLE001
        return sha, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="push the repository through the GitHub Contents API"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="only list the files that would be pushed",
    )
    parser.add_argument("--message", default="", help="commit message")
    args = parser.parse_args()

    token = find_token()
    files = collect_files()

    print(f"repo: {OWNER}/{REPO}    branch: {BRANCH}")
    print(f"files to push: {len(files)}")

    if args.dry_run:
        for path in files:
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            print(f"  {rel}  ({path.stat().st_size} bytes)")
        return 0

    message = args.message or "chore: sync files via API"

    pushed = 0
    unchanged = 0
    failed: list[str] = []

    for path in files:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        content = path.read_bytes()

        remote_sha, remote_content = get_remote_state(token, rel)

        # identical content is skipped -- this line is what makes the push resumable.
        # a line-ending difference is misread as "changed": one extra push, still correct.
        if remote_sha and remote_content is not None and remote_content == content:
            unchanged += 1
            print(f"  --   {rel} (already up to date, skipped)")
            continue

        encoded = base64.b64encode(content).decode("ascii")
        body: dict = {"message": message, "content": encoded, "branch": BRANCH}
        if remote_sha:
            body["sha"] = remote_sha

        # The path must be URL-encoded before it is concatenated into the URL.
        #   The repository may contain Chinese directory or file names, and putting them
        #   straight into a URL raises UnicodeEncodeError: 'ascii' codec can't encode ...
        #   because Python's http.client requires ascii when it builds the request line.
        #   safe="/" keeps the path separator as it is.
        from urllib.parse import quote

        encoded_path = quote(rel, safe="/")

        status, data = api_request(
            "PUT", f"/repos/{OWNER}/{REPO}/contents/{encoded_path}", token, body
        )

        if status in (200, 201):
            pushed += 1
            print(f"  OK   {rel}")
        else:
            failed.append(f"{rel}: HTTP {status} {data.get('message', '')}")
            print(f"  FAIL {rel}: HTTP {status} {data.get('message', '')[:80]}")

    print()
    print(f"pushed {pushed}, skipped {unchanged}, failed {len(failed)}")
    if failed:
        print("failure details:")
        for item in failed:
            print("  " + item)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
