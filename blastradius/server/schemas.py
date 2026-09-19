from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrganizationInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("invalid name")
        return value


class ProjectSettings(OrganizationInput):
    description: str = Field(default="", max_length=2000)
    repository: str = Field(
        default="", max_length=255, pattern=r"^(|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$"
    )
    repository_provider: Literal["manual", "github"] = "manual"
    default_branch: str = Field(default="main", min_length=1, max_length=120)
    environment: str = Field(default="", max_length=100)
    terraform_root: str = Field(default=".", min_length=1, max_length=255)

    @field_validator("default_branch", "environment", "terraform_root")
    @classmethod
    def safe_metadata(cls, value: str) -> str:
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("invalid metadata")
        return value

    @field_validator("terraform_root")
    @classmethod
    def safe_root(cls, value: str) -> str:
        if (
            value.startswith(("/", "\\"))
            or ":" in value
            or "\\" in value
            or ".." in value.split("/")
        ):
            raise ValueError("repository relative path required")
        return value


class ProjectInput(ProjectSettings):
    organization_id: str = Field(min_length=1, max_length=36)


class ProjectUpdate(ProjectSettings):
    archived: bool = False


class RoleInput(StrictModel):
    role: Literal["owner", "admin", "developer", "viewer"]


class InvitationInput(StrictModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    role: Literal["admin", "developer", "viewer"] = "developer"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.casefold()


class AcceptInvitation(StrictModel):
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")


class GateRules(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    block_new_critical_paths: bool = True
    block_new_sensitive_exposure: bool = True
    block_public_admin_ports: bool = True


class AllowedRules(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    public_https: bool = True


class ThresholdRules(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    minimum_security_score: int | None = Field(default=None, ge=0, le=100)


class PolicyInput(StrictModel):
    version: Literal[1] = 1
    gate: GateRules = Field(default_factory=GateRules)
    allowed: AllowedRules = Field(default_factory=AllowedRules)
    thresholds: ThresholdRules = Field(default_factory=ThresholdRules)


class EnterpriseLimits(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    projects: int = Field(ge=1, le=100000)
    analyses_per_month: int = Field(ge=1, le=10000000)
    retention_days: int = Field(ge=1, le=36500)
    members: int = Field(ge=1, le=100000)


class AnalysisInput(StrictModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=36)
    base_label: str = Field(default="baseline", min_length=1, max_length=120)
    candidate_label: str = Field(default="candidate", min_length=1, max_length=120)
    before_files: dict[str, str] | None = None
    after_files: dict[str, str] | None = None
    plan: dict[str, JsonValue] | None = None
    base_ref: str | None = Field(default=None, min_length=1, max_length=120)
    candidate_ref: str | None = Field(default=None, min_length=1, max_length=120)
    base_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")
    candidate_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")

    @model_validator(mode="after")
    def valid_input(self) -> AnalysisInput:
        if self.plan is not None:
            json.dumps(self.plan, allow_nan=False)
            if self.before_files is not None or self.after_files is not None:
                raise ValueError("provide plan or before_files and after_files")
            if "planned_values" not in self.plan and "resource_changes" not in self.plan:
                raise ValueError("plan must be Terraform show -json output")
        elif not self.before_files or not self.after_files:
            raise ValueError("provide nonempty before_files and after_files")
        for files in (self.before_files, self.after_files):
            for name, text in (files or {}).items():
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\.tf", name) or ".." in name:
                    raise ValueError("only simple .tf filenames are allowed")
                if "\x00" in text:
                    raise ValueError("NUL bytes are not accepted")
        return self


class WorkerInput(StrictModel):
    analysis: AnalysisInput
    policy_snapshot: dict[str, JsonValue] | None = None
