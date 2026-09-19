from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

MARKER = "<!-- blastradius-report -->"
BOT_LOGIN = "github-actions[bot]"
API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubClient:
    def __init__(self, token):
        self._token = token
        self._opener = build_opener(_NoRedirect())

    def request(self, method, path, payload=None):
        if not path.startswith("/repos/") or "\n" in path or "\r" in path:
            raise GitHubError("Invalid GitHub API path")
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(API + path, data=body, method=method, headers={
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "BlastRadius",
        })
        try:
            with self._opener.open(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as error:
            raise GitHubError(f"GitHub API returned HTTP {error.code}; report remains in Actions artifacts/summary") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise GitHubError("GitHub API unavailable or returned invalid JSON; report remains in Actions artifacts/summary") from None


@dataclass(frozen=True)
class Publication:
    status: str
    message: str


def publish_report(repository, pr_number, report, *, token=None, head_sha=None, client=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*", repository or ""):
        raise GitHubError("Repository must be owner/name")
    if type(pr_number) is not int or pr_number < 1:
        raise GitHubError("PR number must be a positive integer")
    if head_sha is not None and not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        raise GitHubError("Expected a full PR head SHA")
    if not report.startswith(MARKER):
        raise GitHubError("Refusing to publish a report without the BlastRadius marker")
    if len(report) > 60000:
        raise GitHubError("Report exceeds the comment size budget")
    if not token and client is None:
        return Publication("skipped", "No GitHub token; use the Actions summary/artifacts")
    client = client or GitHubClient(token)
    root = f"/repos/{repository}"
    if head_sha:
        current = client.request("GET", f"{root}/pulls/{pr_number}")
        if current.get("head", {}).get("sha") != head_sha:
            return Publication("stale", "PR head changed; refusing to publish a stale security result")
    existing = None
    for page in range(1, 101):
        comments = client.request("GET", f"{root}/issues/{pr_number}/comments?per_page=100&page={page}")
        if not isinstance(comments, list):
            raise GitHubError("GitHub returned an invalid comments response")
        for comment in comments:
            user = comment.get("user", {})
            if (user.get("login") == BOT_LOGIN and user.get("type") == "Bot"
                    and (comment.get("body") or "").startswith(MARKER)):
                existing = comment
                break
        if existing or len(comments) < 100:
            break
    else:
        raise GitHubError("Comment pagination limit reached; refusing to create a possible duplicate")
    if existing:
        if existing.get("body") == report:
            return Publication("unchanged", "Existing BlastRadius comment is already current")
        comment_id = existing.get("id")
        if type(comment_id) is not int or comment_id < 1:
            raise GitHubError("GitHub returned an invalid comment ID")
        client.request("PATCH", f"{root}/issues/comments/{comment_id}", {"body": report})
        return Publication("updated", "Updated the existing BlastRadius PR comment")
    client.request("POST", f"{root}/issues/{pr_number}/comments", {"body": report})
    return Publication("created", "Created the BlastRadius PR comment")


def main():
    parser = argparse.ArgumentParser(description="Publish one marked BlastRadius PR comment")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--report-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = args.report_file.read_text(encoding="utf-8")
        result = publish_report(args.repository, args.pr, report,
                                token=os.environ.get("GITHUB_TOKEN"), head_sha=args.head_sha)
        print(result.message)
    except (GitHubError, OSError) as error:
        print(f"Comment publication skipped: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
