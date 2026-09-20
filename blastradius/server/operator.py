from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from blastradius.server.auth import current_session, require_user
from blastradius.server.beta import feedback_payload
from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.events import RETENTION_DAYS, event_summary
from blastradius.server.models import (
    Analysis,
    AnalysisFeedback,
    BetaInterest,
    LoginSession,
    Organization,
    Project,
    User,
)
from blastradius.server.persistence import audit
from blastradius.server.plans import catalog
from blastradius.server.quotas import usage_payload

RESOURCES = (
    "users",
    "organizations",
    "projects",
    "plans",
    "usage",
    "failures",
    "beta-requests",
    "feedback",
    "events",
)
FAILURE_CODES = frozenset(
    (
        "analysis_failed",
        "analysis_timeout",
        "dispatch_failed",
        "github_analysis_failed",
        "invalid_analysis_input",
        "invalid_worker_result",
        "resource_limit_exceeded",
        "result_too_large",
        "server_restarted",
        "service_lease_lost",
        "worker_failed",
    )
)


def is_platform_admin(user: User | None, login: LoginSession | None, settings: Settings) -> bool:
    return bool(
        user
        and login
        and login.user_id == user.id
        and login.oidc_authenticated
        and settings.auth_mode == "oidc"
        and user.issuer == settings.oidc_issuer
        and user.email_verified
        and user.email
        and user.id in settings.web_admin_user_ids
    )


def inspect_resource(
    session: Session,
    resource: str,
    limit: int,
    offset: int,
    *,
    trusted_cli: bool = False,
) -> list[dict] | dict:
    if resource not in RESOURCES or not 1 <= limit <= 1000 or not 0 <= offset <= 1_000_000:
        raise ValueError("invalid_inspection")
    if resource == "events":
        return event_summary(session)
    if resource == "plans":
        return catalog()
    if resource == "users":
        return [
            {
                "id": row.id,
                "email_verified": row.email_verified,
                **(
                    {"name": row.name, "email": row.email}
                    if trusted_cli
                    else {"created_at": row.created_at}
                ),
            }
            for row in session.scalars(select(User).order_by(User.id).limit(limit).offset(offset))
        ]
    if resource in ("organizations", "usage"):
        return [
            {
                "id": row.id,
                **usage_payload(session, row),
                **({"name": row.name} if trusted_cli else {"created_at": row.created_at}),
            }
            for row in session.scalars(
                select(Organization).order_by(Organization.id).limit(limit).offset(offset)
            )
        ]
    if resource == "projects":
        return [
            {
                "id": row.id,
                "organization_id": row.organization_id,
                "archived_at": row.archived_at,
                **({"name": row.name} if trusted_cli else {"created_at": row.created_at}),
            }
            for row in session.scalars(
                select(Project).order_by(Project.id).limit(limit).offset(offset)
            )
        ]
    if resource == "failures":
        return [
            {
                "id": row.id,
                "organization_id": row.organization_id,
                "project_id": row.project_id,
                "error": row.error if row.error in FAILURE_CODES else "analysis_failed",
                **(
                    {}
                    if trusted_cli
                    else {
                        "status": "failed",
                        "created_at": row.created_at,
                        "completed_at": row.completed_at,
                    }
                ),
            }
            for row in session.scalars(
                select(Analysis)
                .where(Analysis.status == "failed")
                .order_by(Analysis.created_at.desc(), Analysis.id)
                .limit(limit)
                .offset(offset)
            )
        ]
    if resource == "feedback":
        return [
            feedback_payload(row)
            for row in session.scalars(
                select(AnalysisFeedback)
                .where(AnalysisFeedback.created_at > time.time() - RETENTION_DAYS * 86400)
                .order_by(AnalysisFeedback.created_at.desc(), AnalysisFeedback.id)
                .limit(limit)
                .offset(offset)
            )
        ]
    return [
        {
            "id": row.id,
            "name": row.name,
            "email": row.email,
            "company": row.company,
            "role": row.role,
            "team_size": row.team_size,
            "repository_count": row.repository_count,
            "primary_cloud": row.primary_cloud,
            "source_control": row.source_control,
            "problem": row.problem,
            "privacy_version": row.privacy_version,
            "created_at": row.created_at,
        }
        for row in session.scalars(
            select(BetaInterest)
            .where(BetaInterest.created_at > time.time() - RETENTION_DAYS * 86400)
            .order_by(BetaInterest.created_at.desc(), BetaInterest.id)
            .limit(limit)
            .offset(offset)
        )
    ]


def operator_router(db: Database, settings: Settings) -> APIRouter:
    router = APIRouter()

    def review_endpoint(resource: str):
        def review(
            request: Request,
            limit: int = Query(50, ge=1, le=100),
            offset: int = Query(0, ge=0, le=1_000_000),
        ):
            with db.session(write=True) as session:
                user = require_user(request, session, settings)
                if not is_platform_admin(user, current_session(request, session), settings):
                    raise HTTPException(403, "platform_admin_required")
                audit(
                    session,
                    None,
                    user.id,
                    "operator.inspect",
                    resource,
                    {"limit": limit, "offset": offset},
                )
                data = inspect_resource(session, resource, limit, offset)
                if isinstance(data, dict):
                    return data
                return {
                    "items": data,
                    "limit": limit,
                    "offset": offset,
                    "next_offset": offset + limit if len(data) == limit else None,
                }

        return review

    for resource in RESOURCES:
        router.add_api_route(f"/api/admin/{resource}", review_endpoint(resource), methods=["GET"])
    return router
