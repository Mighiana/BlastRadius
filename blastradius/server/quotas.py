import time
from collections.abc import Collection, Iterable
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from blastradius.server.models import Invitation, Membership, Organization, Project, Usage
from blastradius.server.plans import entitlements


def period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def lock_org(db: Session, organization_id: str) -> Organization:
    org = db.scalar(
        select(Organization)
        .where(Organization.id == organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not org:
        raise HTTPException(404, "not_found")
    return org


def counts(db: Session, org: Organization) -> dict[str, int]:
    return grouped_counts(db, [org.id])[org.id]


def grouped_counts(db: Session, organization_ids: Collection[str]) -> dict[str, dict[str, int]]:
    ids = list(organization_ids)
    result = {
        organization_id: {"projects": 0, "members": 0, "pending_invitations": 0}
        for organization_id in ids
    }
    if not ids:
        return result
    queries = {
        "projects": select(Project.organization_id, func.count())
        .where(Project.organization_id.in_(ids), Project.archived_at.is_(None))
        .group_by(Project.organization_id),
        "members": select(Membership.organization_id, func.count())
        .where(Membership.organization_id.in_(ids))
        .group_by(Membership.organization_id),
        "pending_invitations": select(Invitation.organization_id, func.count())
        .where(
            Invitation.organization_id.in_(ids),
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > time.time(),
        )
        .group_by(Invitation.organization_id),
    }
    for kind, query in queries.items():
        for organization_id, count in db.execute(query):
            result[organization_id][kind] = count
    return result


def quota(db: Session, org: Organization, kind: str) -> None:
    limits = entitlements(org).limits
    if kind == "analyses_per_month":
        usage = usage_row(db, org)
        if usage.analyses >= limits[kind]:
            raise HTTPException(402, "analysis_quota_exceeded")
        usage.analyses += 1
    else:
        current = counts(db, org)
        count = current[kind]
        if kind == "members":
            count += current["pending_invitations"]
        if count >= limits[kind]:
            raise HTTPException(402, f"{kind}_quota_exceeded")


def usage_row(db: Session, org: Organization) -> Usage:
    current_period = period()
    used = db.get(Usage, (org.id, current_period))
    if used is None:
        used = Usage(organization_id=org.id, period=current_period, analyses=0, exports=0)
        db.add(used)
    return used


def usage_payload(db: Session, org: Organization) -> dict:
    current_period = period()
    used = db.get(Usage, (org.id, current_period))
    return _payload(org, current_period, used, counts(db, org))


def usage_payloads(db: Session, orgs: Iterable[Organization]) -> dict[str, dict]:
    by_id = {org.id: org for org in orgs}
    if not by_id:
        return {}
    current_period = period()
    used = {
        row.organization_id: row
        for row in db.scalars(
            select(Usage).where(
                Usage.organization_id.in_(list(by_id)), Usage.period == current_period
            )
        )
    }
    current = grouped_counts(db, by_id)
    return {
        organization_id: _payload(
            org, current_period, used.get(organization_id), current[organization_id]
        )
        for organization_id, org in by_id.items()
    }


def _payload(
    org: Organization, current_period: str, used: Usage | None, current: dict[str, int]
) -> dict:
    plan = entitlements(org)
    return {
        "period": current_period,
        "analyses": used.analyses if used else 0,
        "exports": used.exports if used else 0,
        **current,
        "limits": plan.limits,
        "features": plan.features,
        "plan": org.plan,
    }
