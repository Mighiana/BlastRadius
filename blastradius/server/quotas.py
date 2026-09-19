from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from blastradius.server.models import Membership, Organization, Project, Usage

PLANS = {
    "free": {"analyses_per_month": 20, "projects": 3, "members": 1},
    "pro": {"analyses_per_month": 500, "projects": 20, "members": 5},
    "team": {"analyses_per_month": 5000, "projects": 100, "members": 25},
}


def period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def lock_org(db: Session, organization_id: str) -> Organization:
    org = db.scalar(
        select(Organization).where(Organization.id == organization_id).with_for_update()
    )
    if not org:
        raise HTTPException(404, "not_found")
    return org


def quota(db: Session, org: Organization, kind: str) -> None:
    limits = PLANS.get(org.plan, PLANS["free"])
    if kind == "analyses_per_month":
        current_period = period()
        usage = db.get(Usage, (org.id, current_period))
        if usage is None:
            usage = Usage(organization_id=org.id, period=current_period, analyses=0)
            db.add(usage)
        if usage.analyses >= limits[kind]:
            raise HTTPException(402, "analysis_quota_exceeded")
        usage.analyses += 1
    else:
        model = Project if kind == "projects" else Membership
        count = (
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.organization_id == org.id)
            )
            or 0
        )
        if count >= limits[kind]:
            raise HTTPException(402, f"{kind}_quota_exceeded")


def usage_payload(db: Session, org: Organization) -> dict:
    current_period = period()
    used = db.get(Usage, (org.id, current_period))
    return {
        "period": current_period,
        "analyses": used.analyses if used else 0,
        "limits": PLANS.get(org.plan, PLANS["free"]),
        "plan": org.plan,
    }
