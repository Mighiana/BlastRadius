from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from blastradius.security.decision import Decision


class Score(BaseModel):
    model_config = ConfigDict(strict=True)
    before: int = Field(ge=0, le=100)
    after: int = Field(ge=0, le=100)
    delta: int


class Snapshot(BaseModel):
    model_config = ConfigDict(strict=True)
    label: str
    complete: bool
    paths_truncated: bool
    score: int = Field(ge=0, le=100)
    risk_level: str
    attack_paths: list[dict]
    score_breakdown: list[dict]
    exposed_resources: list[str]
    reachable_sensitive: list[str]
    graph: dict


class Finding(BaseModel):
    model_config = ConfigDict(strict=True)
    label: str
    detail: str
    delta: int
    severity: str


class Remediation(BaseModel):
    model_config = ConfigDict(strict=True)
    recommendations: list[dict]
    patched_files: dict[str, str]
    diff: str
    can_autofix: bool


class Result(BaseModel):
    model_config = ConfigDict(strict=True)
    schema_version: int
    analysis_complete: bool
    decision: str
    passed: bool
    headline: str
    verdict: str
    score: Score
    before: Snapshot
    after: Snapshot
    findings: list[Finding]
    new_attack_paths: list[dict]
    removed_attack_paths: list[dict]
    new_critical_paths: list[dict]
    removed_critical_paths: list[dict]
    newly_exposed: list[str]
    newly_reachable_sensitive: list[str]
    new_nodes: list[str]
    removed_nodes: list[str]
    new_edges: list[dict]
    removed_edges: list[dict]
    responsible_change: str
    responsible_changes: list[dict]
    diagnostics: list[dict]
    limitations: list[str]
    remediation: Remediation
    reports: dict


def validate_result(result: dict) -> None:
    parsed = Result.model_validate(result)
    decision = Decision(parsed.decision)
    complete = parsed.before.complete and parsed.after.complete
    if (
        parsed.schema_version != 1
        or parsed.analysis_complete != complete
        or (complete and (parsed.before.paths_truncated or parsed.after.paths_truncated))
        or (decision is Decision.SAFE and not complete)
        or parsed.passed != decision.passed
        or parsed.score.before != parsed.before.score
        or parsed.score.after != parsed.after.score
        or parsed.score.delta != parsed.score.after - parsed.score.before
    ):
        raise ValueError("inconsistent_result")
    markdown = parsed.reports["markdown"]
    if not isinstance(markdown, str) or [
        line for line in markdown.splitlines() if line.startswith("Decision: ")
    ] != [f"Decision: {decision.value}"]:
        raise ValueError("inconsistent_markdown")
    runs = parsed.reports["sarif"]["runs"]
    if not isinstance(runs, list) or len(runs) != 1:
        raise ValueError("invalid_sarif")
    properties = runs[0]["properties"]
    if (
        properties["decision"] != decision.value
        or properties["analysisComplete"] is not complete
        or properties["pathsTruncated"]
        is not (parsed.before.paths_truncated or parsed.after.paths_truncated)
    ):
        raise ValueError("inconsistent_sarif")


def worker_response(response: object) -> dict:
    if not isinstance(response, dict):
        return {"error": "invalid_worker_result"}
    if set(response) == {"error"} and isinstance(response["error"], str) and response["error"]:
        return response
    try:
        if set(response) != {"result"} or not isinstance(response["result"], dict):
            raise ValueError("invalid_envelope")
        validate_result(response["result"])
    except (ValueError, ValidationError, KeyError, TypeError, IndexError):
        return {"error": "invalid_worker_result"}
    return response
