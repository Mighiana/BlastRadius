from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Id = Annotated[int, Field(gt=0, le=9223372036854775807, strict=True)]
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
FullName = Annotated[str, Field(max_length=255, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class Identity(ProviderModel):
    id: Id


class Account(Identity):
    login: str = Field(min_length=1, max_length=100)


class Installation(Identity):
    app_id: Id
    account: Account
    permissions: dict[str, str]
    suspended_at: str | None


class Repository(Identity):
    full_name: FullName
    owner: Account
    default_branch: str = Field(min_length=1, max_length=120)

    @field_validator("full_name")
    @classmethod
    def valid_full_name(cls, value: str) -> str:
        if any(part in (".", "..") for part in value.split("/")):
            raise ValueError("invalid_repository_name")
        return value


class Repositories(ProviderModel):
    total_count: int
    repositories: list[Repository]


class Ref(ProviderModel):
    sha: Sha
    ref: str = Field(min_length=1, max_length=120)
    repo: Identity

    @field_validator("ref")
    @classmethod
    def valid_ref(cls, value: str) -> str:
        if (
            any(ord(c) < 33 or ord(c) == 127 or c in "~^:?*[\\" for c in value)
            or ".." in value
            or "@{" in value
            or value.startswith(("/", "."))
            or value.endswith(("/", ".", ".lock"))
            or "//" in value
        ):
            raise ValueError("unsupported_ref")
        return value


class Pull(ProviderModel):
    number: Id
    state: Literal["open", "closed"]
    base: Ref
    head: Ref


class PullEvent(ProviderModel):
    action: Literal["opened", "synchronize", "reopened"]
    number: Id
    installation: Identity
    repository: Identity
    pull_request: Pull


class LifecycleEvent(ProviderModel):
    action: str = Field(max_length=40)
    installation: Identity
    repositories_removed: list[Identity] = Field(default_factory=list, max_length=10000)


class Token(ProviderModel):
    token: str = Field(min_length=1, max_length=16384, repr=False)
    expires_at: str
    permissions: dict[str, str]


class TreeEntry(ProviderModel):
    path: str = Field(min_length=1, max_length=1024)
    mode: str
    type: str
    sha: Sha
    size: int = Field(default=0, ge=0)


class Tree(ProviderModel):
    sha: Sha
    truncated: bool
    tree: list[TreeEntry] = Field(max_length=10000)


class Blob(ProviderModel):
    sha: Sha
    encoding: Literal["base64"]
    size: int = Field(ge=0)
    content: str


class BlobIdentity(ProviderModel):
    sha: Sha


class GitCommit(BlobIdentity):
    tree: BlobIdentity


class CommentUser(Identity):
    type: str


class Comment(Identity):
    body: str | None = None
    user: CommentUser
    performed_via_github_app: Identity | None = None


class Check(Identity):
    head_sha: Sha
    external_id: str | None
    app: Identity


class Checks(ProviderModel):
    total_count: int
    check_runs: list[Check]


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    installation_id: Id
    repository_id: Id
