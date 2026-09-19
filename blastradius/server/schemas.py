from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrganizationInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)


class ProjectInput(OrganizationInput):
    organization_id: str = Field(min_length=1, max_length=36)


class MemberInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=36)
    role: Literal["member", "viewer"] = "member"


class AnalysisInput(StrictModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=36)
    base_label: str = Field(default="baseline", min_length=1, max_length=120)
    candidate_label: str = Field(default="candidate", min_length=1, max_length=120)
    before_files: dict[str, str] | None = None
    after_files: dict[str, str] | None = None
    plan: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def valid_input(self) -> AnalysisInput:
        if self.plan is not None:
            json.dumps(self.plan, allow_nan=False)
            if self.before_files is not None or self.after_files is not None:
                raise ValueError("provide plan or before_files and after_files")
            if (
                "planned_values" not in self.plan
                and "resource_changes" not in self.plan
            ):
                raise ValueError("plan must be Terraform show -json output")
        elif not self.before_files or not self.after_files:
            raise ValueError("provide nonempty before_files and after_files")
        for files in (self.before_files, self.after_files):
            for name, text in (files or {}).items():
                if (
                    not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\.tf", name)
                    or ".." in name
                ):
                    raise ValueError("only simple .tf filenames are allowed")
                if "\x00" in text:
                    raise ValueError("NUL bytes are not accepted")
        return self


class CheckoutInput(StrictModel):
    plan: Literal["pro", "team"]
