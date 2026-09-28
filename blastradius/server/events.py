from __future__ import annotations

import time
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from blastradius.server.models import Analysis, CommercialLock, ProductEvent

EVENT_NAMES = (
    "account_created",
    "workspace_created",
    "project_created",
    "analysis_started",
    "analysis_completed",
    "analysis_failed",
    "block_result",
    "review_result",
    "safe_result",
    "report_exported",
    "github_connected",
    "beta_interest_submitted",
    "feedback_submitted",
)
EVENT_LIMIT = 100_000
RETENTION_DAYS = 90


def lock_commercial(db: Session) -> None:
    if db.scalar(select(CommercialLock).where(CommercialLock.id == 1).with_for_update()) is None:
        raise RuntimeError("commercial_storage_not_ready")


def opaque_id(value: str | None) -> str | None:
    try:
        return str(UUID(value)) if value else None
    except ValueError:
        return None


def record_event(
    db: Session,
    name: str,
    *,
    user_id: str | None = None,
    organization_id: str | None = None,
    project_id: str | None = None,
    analysis_id: str | None = None,
) -> None:
    if name not in EVENT_NAMES:
        raise ValueError("unknown_product_event")
    lock_commercial(db)
    count = db.scalar(select(func.count()).select_from(ProductEvent)) or 0
    if count >= EVENT_LIMIT:
        oldest = (
            select(ProductEvent.id)
            .order_by(ProductEvent.created_at, ProductEvent.id)
            .limit(count - EVENT_LIMIT + 1)
        )
        db.execute(delete(ProductEvent).where(ProductEvent.id.in_(oldest)))
    db.add(
        ProductEvent(
            name=name,
            user_id=opaque_id(user_id),
            organization_id=opaque_id(organization_id),
            project_id=opaque_id(project_id),
            analysis_id=opaque_id(analysis_id),
        )
    )
    db.flush()


def analysis_event(db: Session, job: Analysis, name: str) -> None:
    record_event(
        db,
        name,
        user_id=job.created_by,
        organization_id=job.organization_id,
        project_id=job.project_id,
        analysis_id=job.id,
    )


def terminal_events(db: Session, job: Analysis) -> None:
    if job.status == "failed":
        analysis_event(db, job, "analysis_failed")
    elif job.status == "succeeded":
        analysis_event(db, job, "analysis_completed")
        decision = {
            "BLOCK CHANGE": "block_result",
            "REVIEW REQUIRED": "review_result",
            "SAFE TO MERGE": "safe_result",
        }.get(job.decision or "")
        if decision:
            analysis_event(db, job, decision)


def event_summary(db: Session) -> dict:
    since = time.time() - RETENTION_DAYS * 86400
    counts = {
        name: count
        for name, count in db.execute(
            select(ProductEvent.name, func.count())
            .where(ProductEvent.created_at > since)
            .group_by(ProductEvent.name)
        ).all()
    }
    return {
        "retention_days": RETENTION_DAYS,
        "max_records": EVENT_LIMIT,
        "counts": {name: counts.get(name, 0) for name in EVENT_NAMES},
        "active_workspaces": db.scalar(
            select(func.count(func.distinct(ProductEvent.organization_id))).where(
                ProductEvent.created_at > since
            )
        )
        or 0,
    }
