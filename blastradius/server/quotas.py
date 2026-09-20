import time
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
    return {
        "projects": db.scalar(
            select(func.count())
            .select_from(Project)
            .where(Project.organization_id == org.id, Project.archived_at.is_(None))
        )
        or 0,
        "members": db.scalar(
            select(func.count()).select_from(Membership).where(Membership.organization_id == org.id)
        )
        or 0,
        "pending_invitations": db.scalar(
            select(func.count())
            .select_from(Invitation)
            .where(
                Invitation.organization_id == org.id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > time.time(),
            )
        )
        or 0,
    }


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
    return {
        "period": current_period,
        "analyses": used.analyses if used else 0,
        "exports": used.exports if used else 0,
        **counts(db, org),
        "limits": entitlements(org).limits,
        "features": entitlements(org).features,
        "plan": org.plan,
    }
