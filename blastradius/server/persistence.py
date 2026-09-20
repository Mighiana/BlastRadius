import json
import time

from fastapi import HTTPException
from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from blastradius.server.auth import membership
from blastradius.server.db import Database
from blastradius.server.models import (
    Analysis,
    AnalysisArtifact,
    AttackPath,
    AttackPathHop,
    AuditEvent,
    Finding,
    Organization,
    Project,
    User,
)
from blastradius.server.plans import PLANS, entitlements
from blastradius.server.quotas import lock_org
from blastradius.server.results import validate_result


def audit(
    db: Session,
    org_id: str | None,
    actor: str,
    action: str,
    target: str,
    details: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            organization_id=org_id,
            actor=actor,
            action=action,
            target_id=target,
            details=details or {},
        )
    )


def effective_policy(org: Organization, project: Project) -> dict:
    plan = entitlements(org)
    if plan.advanced_policy and project.policy is not None:
        return {"source": "project", "version": project.policy_version, "rules": project.policy}
    if plan.organization_policy and org.policy is not None:
        return {"source": "organization", "version": org.policy_version, "rules": org.policy}
    return {"source": "default", "version": 1, "rules": None}


def cutoff(org: Organization, now: float | None = None) -> float:
    return (time.time() if now is None else now) - entitlements(org).retention_days * 86400


def visible_analysis(db: Session, user: User, analysis_id: str) -> tuple[Analysis, Organization]:
    job = db.get(Analysis, analysis_id)
    if job is None:
        raise HTTPException(404, "not_found")
    membership(db, user, job.organization_id)
    org = db.get(Organization, job.organization_id)
    assert org is not None
    if job.created_at <= cutoff(org):
        raise HTTPException(404, "not_found")
    return job, org


def public_result(result: dict | None, sarif: bool) -> dict | None:
    if result is None:
        return None
    if sarif:
        return result
    return {**result, "reports": {k: v for k, v in result["reports"].items() if k != "sarif"}}


def persist_result(db: Session, job: Analysis, result: dict) -> None:
    validate_result(result)
    job.result = result
    job.decision = result["decision"]
    job.score_before = result["score"]["before"]
    job.score_after = result["score"]["after"]
    job.risk_before = result["before"]["risk_level"]
    job.risk_after = result["after"]["risk_level"]
    job.critical_paths_added = len(result["new_critical_paths"])
    job.critical_paths_removed = len(result["removed_critical_paths"])
    job.normalized_version = 1
    for item in result["findings"]:
        db.add(
            Finding(
                analysis_id=job.id,
                type="decision_reason",
                severity=item["severity"],
                title=item["label"],
                description=item["detail"],
                evidence=item,
            )
        )
    for phase in ("before", "after"):
        for item in result[phase]["attack_paths"]:
            path = AttackPath(
                analysis_id=job.id,
                phase=phase,
                severity=item["severity"],
                path_key=item["id"],
                nodes=item["nodes"],
                labels=item["labels"],
                explanation=item["explanation"],
                reaches_sensitive=item["reaches_sensitive"],
            )
            db.add(path)
            db.flush()
            for index, edge in enumerate(item["edges"]):
                db.add(
                    AttackPathHop(
                        path_id=path.id,
                        position=index,
                        source_node=edge["source"],
                        target_node=edge["target"],
                        relationship=edge["relationship"],
                        evidence=edge,
                    )
                )
    for format, media_type, content in (
        ("json", "application/json", json.dumps(result)),
        ("markdown", "text/markdown", result["reports"]["markdown"]),
        ("sarif", "application/sarif+json", json.dumps(result["reports"]["sarif"])),
    ):
        db.add(
            AnalysisArtifact(
                analysis_id=job.id,
                format=format,
                media_type=media_type,
                content=content,
            )
        )


def cleanup(db: Database, limit: int = 100) -> int:
    if not 1 <= limit <= 10000:
        raise ValueError("limit must be between 1 and 10000")
    now = time.time()
    removed = 0
    retention_days = case(
        (
            Organization.plan == "enterprise",
            func.coalesce(
                Organization.plan_limits["retention_days"].as_integer(),
                PLANS["enterprise"].retention_days,
            ),
        ),
        *((Organization.plan == plan.code, plan.retention_days) for plan in PLANS.values()),
        else_=PLANS["free"].retention_days,
    )
    with db.session(write=True) as session:
        candidates = session.execute(
            select(Analysis.organization_id, Analysis.id)
            .join(Organization, Organization.id == Analysis.organization_id)
            .where(Analysis.created_at <= now - retention_days * 86400)
            .order_by(Analysis.organization_id, Analysis.created_at, Analysis.id)
            .limit(limit)
        ).all()
        by_org: dict[str, list[str]] = {}
        for org_id, analysis_id in candidates:
            by_org.setdefault(org_id, []).append(analysis_id)
        for org_id, candidate_ids in by_org.items():
            try:
                org = lock_org(session, org_id)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                continue
            ids = list(
                session.scalars(
                    select(Analysis.id)
                    .where(
                        Analysis.id.in_(candidate_ids),
                        Analysis.organization_id == org.id,
                        Analysis.created_at <= cutoff(org, now),
                    )
                    .order_by(Analysis.created_at, Analysis.id)
                )
            )
            if ids:
                session.execute(delete(Analysis).where(Analysis.id.in_(ids)))
                audit(
                    session, org.id, "operator", "retention.cleanup", org.id, {"removed": len(ids)}
                )
                removed += len(ids)
    return removed
