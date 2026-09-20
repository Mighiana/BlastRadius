from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
import time
from datetime import datetime, timezone
from pathlib import PurePosixPath
from types import TracebackType
from typing import TypeVar

import httpx
from authlib.jose import jwt
from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from blastradius.server.config import Settings
from blastradius.server.github_types import (
    Blob,
    GitCommit,
    Installation,
    Pull,
    Repositories,
    Repository,
    Token,
    Tree,
)

Model = TypeVar("Model", bound=BaseModel)
READ_PERMISSIONS = {"contents": "read", "pull_requests": "read", "metadata": "read"}
WRITE_PERMISSIONS = {
    "contents": "read",
    "pull_requests": "write",
    "checks": "write",
    "metadata": "read",
}
MAX_RESPONSE = 2 * 1024 * 1024


class GitHubError(Exception):
    def __init__(self, code: str, retryable: bool = False, uncertain: bool = False):
        super().__init__(code)
        self.code, self.retryable, self.uncertain = code, retryable, uncertain


class GitHubAPI:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.client = httpx.Client(
            base_url="https://api.github.com",
            timeout=httpx.Timeout(5, connect=3),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self.remaining = 100
        self.deadline = time.monotonic() + 90

    def __enter__(self) -> GitHubAPI:
        return self

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.client.close()

    def request(
        self, method: str, path: str, token: str, body: dict[str, JsonValue] | None = None
    ) -> JsonValue:
        if not path.startswith("/") or path.startswith("//") or "://" in path:
            raise GitHubError("invalid_api_path")
        for attempt in range(3 if method == "GET" else 1):
            self.remaining -= 1
            if self.remaining < 0 or time.monotonic() >= self.deadline:
                raise GitHubError("github_budget_exceeded")
            try:
                with self.client.stream(
                    method,
                    path,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "Accept-Encoding": "identity",
                    },
                    json=body,
                ) as response:
                    if response.status_code in {429, 500, 502, 503, 504}:
                        raise GitHubError("github_unavailable", True, method != "GET")
                    if response.status_code in {401, 403, 404, 422}:
                        raise GitHubError("github_access_denied")
                    if not 200 <= response.status_code < 300:
                        raise GitHubError("github_response_invalid", uncertain=method != "GET")
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise GitHubError("github_response_encoding", uncertain=method != "GET")
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > MAX_RESPONSE or time.monotonic() >= self.deadline:
                            raise GitHubError("github_response_limit", uncertain=method != "GET")
                    return TypeAdapter(JsonValue).validate_json(bytes(chunks))
            except httpx.HTTPError:
                error = GitHubError("github_unavailable", True, method != "GET")
            except (ValidationError, ValueError, RecursionError):
                raise GitHubError("github_response_invalid", uncertain=method != "GET") from None
            except GitHubError as exc:
                error = exc
            if not error.retryable or method != "GET" or attempt == 2:
                raise error from None
            time.sleep(0.25 * (attempt + 1))
        raise GitHubError("github_unavailable", True)

    def model(
        self,
        cls: type[Model],
        method: str,
        path: str,
        token: str,
        body: dict[str, JsonValue] | None = None,
    ) -> Model:
        try:
            return cls.model_validate(self.request(method, path, token, body))
        except ValidationError:
            raise GitHubError("github_response_invalid", uncertain=method != "GET") from None

    def app_token(self) -> str:
        path = self.settings.github_private_key_file
        if not self.settings.github_enabled or path is None:
            raise GitHubError("github_not_configured")
        try:
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as pem:
                info = os.fstat(pem.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                    raise GitHubError("github_key_unavailable")
                key = pem.read(16385)
                if len(key) > 16384:
                    raise GitHubError("github_key_unavailable")
            now = int(time.time())
            encoded = jwt.encode(
                {"alg": "RS256"},
                {"iat": now - 60, "exp": now + 540, "iss": str(self.settings.github_app_id)},
                key,
            )
            return encoded.decode("ascii")
        except (OSError, ValueError, TypeError):
            raise GitHubError("github_key_unavailable") from None

    def installation(self, installation_id: int, account_id: int) -> Installation:
        record = self.model(
            Installation, "GET", f"/app/installations/{installation_id}", self.app_token()
        )
        if (
            record.id != installation_id
            or record.app_id != self.settings.github_app_id
            or record.account.id != account_id
            or record.suspended_at is not None
            or any(record.permissions.get(k) != v for k, v in WRITE_PERMISSIONS.items())
        ):
            raise GitHubError("github_installation_unavailable")
        return record

    def installation_token(
        self, installation_id: int, repository_id: int, write: bool = False
    ) -> str:
        permissions = WRITE_PERMISSIONS if write else READ_PERMISSIONS
        record = self.model(
            Token,
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            self.app_token(),
            {"repository_ids": [repository_id], "permissions": dict(permissions)},
        )
        try:
            expires = datetime.fromisoformat(record.expires_at.replace("Z", "+00:00"))
            seconds = (expires - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError):
            raise GitHubError("github_token_invalid") from None
        if not 60 < seconds <= 3660 or record.permissions != permissions:
            raise GitHubError("github_token_invalid")
        return record.token

    def repository(self, token: str, repository_id: int, account_id: int) -> Repository:
        response = self.model(Repositories, "GET", "/installation/repositories?per_page=2", token)
        if (
            response.total_count != 1
            or len(response.repositories) != 1
            or response.repositories[0].id != repository_id
            or response.repositories[0].owner.id != account_id
        ):
            raise GitHubError("github_repository_mismatch")
        return response.repositories[0]

    def pull(self, token: str, repository: Repository, number: int) -> Pull:
        pull = self.model(Pull, "GET", f"/repos/{repository.full_name}/pulls/{number}", token)
        if pull.number != number or pull.base.repo.id != repository.id or pull.state != "open":
            raise GitHubError("github_pull_mismatch")
        return pull

    def snapshot(self, token: str, repository: Repository, sha: str, root: str) -> dict[str, str]:
        prefix = f"/repos/{repository.full_name}/git"
        commit = self.model(GitCommit, "GET", f"{prefix}/commits/{sha}", token)
        if commit.sha != sha:
            raise GitHubError("github_commit_mismatch")
        tree = self.model(Tree, "GET", f"{prefix}/trees/{commit.tree.sha}?recursive=1", token)
        if tree.truncated or tree.sha != commit.tree.sha:
            raise GitHubError("github_tree_incomplete")
        root_prefix = "" if root == "." else root.rstrip("/") + "/"
        files: dict[str, str] = {}
        total = 0
        seen: set[str] = set()
        for entry in tree.tree:
            path = PurePosixPath(entry.path)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in entry.path
                or str(path) != entry.path
                or entry.path in seen
            ):
                raise GitHubError("github_unsafe_tree")
            seen.add(entry.path)
            if not entry.path.startswith(root_prefix):
                continue
            relative = entry.path[len(root_prefix) :]
            if entry.mode in {"120000", "160000"}:
                raise GitHubError("github_unsupported_tree")
            if not relative.endswith((".tf", ".tf.json", ".tfvars", ".tfvars.json")):
                continue
            if "/" in relative or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\.tf", relative
            ):
                raise GitHubError("github_unsupported_terraform")
            if ".." in relative or entry.type != "blob" or entry.mode not in {"100644", "100755"}:
                raise GitHubError("github_unsupported_terraform")
            total += entry.size
            if total > self.settings.max_body_bytes // 2 or len(files) >= self.settings.max_files:
                raise GitHubError("github_source_limit")
            blob = self.model(Blob, "GET", f"{prefix}/blobs/{entry.sha}", token)
            try:
                content = base64.b64decode("".join(blob.content.split()), validate=True)
                digest = hashlib.sha1(
                    b"blob " + str(len(content)).encode() + b"\0" + content,
                    usedforsecurity=False,
                ).hexdigest()
                if blob.sha != entry.sha or digest != entry.sha or blob.size != entry.size:
                    raise GitHubError("github_blob_mismatch")
                if len(content) != entry.size or b"\0" in content:
                    raise GitHubError("github_blob_invalid")
                text = content.decode("utf-8")
                if text.startswith("version https://git-lfs.github.com/spec/"):
                    raise GitHubError("github_unsupported_terraform")
                files[relative] = text
            except (UnicodeError, binascii.Error):
                raise GitHubError("github_blob_invalid") from None
        if not files:
            raise GitHubError("github_no_terraform")
        if len(json.dumps(files).encode()) > self.settings.max_body_bytes:
            raise GitHubError("github_source_limit")
        return files
