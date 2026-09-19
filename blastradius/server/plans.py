from dataclasses import dataclass, replace
from typing import Literal

from fastapi import HTTPException

from blastradius.server.models import Organization

Feature = Literal["advanced_policy", "sarif", "team", "organization_policy", "audit"]


@dataclass(frozen=True)
class Plan:
    code: str
    monthly_price_usd: int | None
    projects: int
    analyses_per_month: int
    retention_days: int
    members: int
    advanced_policy: bool = False
    sarif: bool = False
    team: bool = False
    organization_policy: bool = False
    audit: bool = False

    @property
    def limits(self) -> dict[str, int]:
        return {
            "projects": self.projects,
            "analyses_per_month": self.analyses_per_month,
            "retention_days": self.retention_days,
            "members": self.members,
        }

    @property
    def features(self) -> dict[str, bool]:
        return {
            "advanced_policy": self.advanced_policy,
            "sarif": self.sarif,
            "team": self.team,
            "organization_policy": self.organization_policy,
            "audit": self.audit,
            "json": True,
            "markdown": True,
            "payments": False,
            "priority_queue": False,
            "saml": False,
        }


PLANS = {
    "free": Plan("free", 0, 1, 25, 7, 1),
    "pro": Plan("pro", 49, 5, 500, 90, 1, advanced_policy=True, sarif=True),
    "team": Plan("team", 149, 25, 5000, 365, 25, True, True, True, True, True),
    "enterprise": Plan("enterprise", None, 25, 5000, 365, 25, True, True, True, True, True),
}


def entitlements(org: Organization) -> Plan:
    plan = PLANS.get(org.plan, PLANS["free"])
    if org.plan == "enterprise" and org.plan_limits:
        plan = replace(
            plan,
            projects=org.plan_limits.get("projects", plan.projects),
            analyses_per_month=org.plan_limits.get("analyses_per_month", plan.analyses_per_month),
            retention_days=org.plan_limits.get("retention_days", plan.retention_days),
            members=org.plan_limits.get("members", plan.members),
        )
    return plan


def require_feature(org: Organization, feature: Feature) -> None:
    if not entitlements(org).features[feature]:
        raise HTTPException(402, f"{feature}_not_entitled")


def catalog() -> dict:
    return {
        "payments_enabled": False,
        "mode": "commercial_beta",
        "plans": [
            {
                "code": plan.code,
                "monthly_price_usd": plan.monthly_price_usd,
                "price_status": "free" if plan.code == "free" else "proposed",
                "assignment": "signup" if plan.code == "free" else "operator_beta",
                "limits": plan.limits,
                "features": plan.features,
                "configurable": plan.code == "enterprise",
            }
            for plan in PLANS.values()
        ],
    }
