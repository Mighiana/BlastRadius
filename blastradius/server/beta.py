from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import ConfigDict, Field, StrictBool, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from blastradius.server.auth import require_csrf, require_user
from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.events import RETENTION_DAYS, lock_commercial, record_event
from blastradius.server.models import Analysis, AnalysisFeedback, BetaInterest, ProductEvent
from blastradius.server.persistence import audit, visible_analysis
from blastradius.server.schemas import StrictModel, email_identity

PRIVACY_VERSION = "2026-09-20"
PRIVACY_NOTICE = (
    "We collect these details for operator review of beta interest under a 90-day retention policy. "
    "Only authorized platform operators can review them. Submission does not create an "
    "account, guarantee access, or send an email. Do not include Terraform, credentials, "
    "or private infrastructure details. Optional fields may be left blank."
)
LEAD_LIMIT = 10_000
FEEDBACK_LIMIT = 50_000


class BetaInterestInput(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)
    company: str = Field(default="", max_length=120)
    role: str = Field(default="", max_length=80)
    team_size: int | None = Field(default=None, ge=1, le=100_000)
    repository_count: int | None = Field(default=None, ge=0, le=100_000)
    primary_cloud: Literal["aws", "azure", "gcp", "multiple", "other", "none"] | None = None
    source_control: Literal["github", "gitlab", "both", "other", "none"] | None = None
    problem: str = Field(default="", max_length=1000)
    privacy_version: Literal["2026-09-20"]
    privacy_consent: StrictBool

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        normalized = email_identity(value)
        if normalized is None:
            raise ValueError("invalid_email")
        return normalized

    @field_validator("privacy_consent")
    @classmethod
    def consent_required(cls, value: bool) -> bool:
        if not value:
            raise ValueError("consent_required")
        return value

    @field_validator("name", "company", "role", "problem")
    @classmethod
    def plain_text(cls, value: str) -> str:
        if any(not c.isprintable() and c != "\n" for c in value):
            raise ValueError("invalid_text")
        return value


class FeedbackInput(StrictModel):
    useful: StrictBool
    message: str = Field(default="", max_length=1000)

    @field_validator("message")
    @classmethod
    def plain_text(cls, value: str) -> str:
        return BetaInterestInput.plain_text(value)


def strict_origin(request: Request, settings: Settings) -> None:
    if request.headers.get("origin") != settings.public_url.rstrip("/"):
        raise HTTPException(403, "invalid_origin")


def feedback_payload(row: AnalysisFeedback) -> dict:
    return {
        "id": row.id,
        "analysis_id": row.analysis_id,
        "project_id": row.project_id,
        "organization_id": row.organization_id,
        "user_id": row.user_id,
        "useful": row.useful,
        "message": row.message,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def require_capacity(
    session: Session, model: type[BetaInterest] | type[AnalysisFeedback], limit: int
) -> None:
    if (session.scalar(select(func.count()).select_from(model)) or 0) >= limit:
        raise HTTPException(503, "submission_storage_full")


def cleanup_commercial(db: Database, limit: int = 100) -> dict[str, int]:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    counts = {}
    with db.session(write=True) as session:
        lock_commercial(session)
        for model in (BetaInterest, AnalysisFeedback, ProductEvent):
            ids = list(
                session.scalars(
                    select(model.id)
                    .where(model.created_at <= time.time() - RETENTION_DAYS * 86400)
                    .order_by(model.created_at, model.id)
                    .limit(limit)
                )
            )
            if ids:
                session.execute(delete(model).where(model.id.in_(ids)))
            counts[model.__tablename__] = len(ids)
        audit(session, None, "operator", "commercial.cleanup", "commercial", counts)
    return counts


def beta_router(db: Database, settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/api/beta-interest/privacy")
    def privacy():
        return {
            "version": PRIVACY_VERSION,
            "notice": PRIVACY_NOTICE,
            "retention_days": RETENTION_DAYS,
        }

    @router.post("/api/beta-interest", status_code=201)
    def submit_interest(body: BetaInterestInput, request: Request):
        strict_origin(request, settings)
        with db.session(write=True) as session:
            require_csrf(request, session, settings)
            lock_commercial(session)
            require_capacity(session, BetaInterest, LEAD_LIMIT)
            row = BetaInterest(**body.model_dump(exclude={"privacy_consent"}))
            session.add(row)
            record_event(session, "beta_interest_submitted")
        return {"status": "stored", "message": "Your beta interest has been saved."}

    @router.get("/api/analyses/{analysis_id}/feedback")
    def get_feedback(analysis_id: str, request: Request):
        with db.session() as session:
            user = require_user(request, session, settings)
            job, _ = visible_analysis(session, user, analysis_id)
            row = session.scalar(
                select(AnalysisFeedback).where(
                    AnalysisFeedback.analysis_id == job.id,
                    AnalysisFeedback.user_id == user.id,
                    AnalysisFeedback.created_at > time.time() - RETENTION_DAYS * 86400,
                )
            )
            return {"feedback": feedback_payload(row) if row else None}

    @router.put("/api/analyses/{analysis_id}/feedback")
    def submit_feedback(analysis_id: str, body: FeedbackInput, request: Request):
        strict_origin(request, settings)
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            job, _ = visible_analysis(session, user, analysis_id)
            if job.status not in ("succeeded", "failed"):
                raise HTTPException(409, "analysis_not_terminal")
            session.scalar(select(Analysis).where(Analysis.id == job.id).with_for_update())
            lock_commercial(session)
            row = session.scalar(
                select(AnalysisFeedback).where(
                    AnalysisFeedback.analysis_id == job.id,
                    AnalysisFeedback.user_id == user.id,
                )
            )
            if row is None:
                require_capacity(session, AnalysisFeedback, FEEDBACK_LIMIT)
                row = AnalysisFeedback(
                    analysis_id=job.id,
                    project_id=job.project_id,
                    organization_id=job.organization_id,
                    user_id=user.id,
                    useful=body.useful,
                    message=body.message,
                )
                session.add(row)
                record_event(
                    session,
                    "feedback_submitted",
                    user_id=user.id,
                    organization_id=job.organization_id,
                    project_id=job.project_id,
                    analysis_id=job.id,
                )
            else:
                if row.created_at <= time.time() - RETENTION_DAYS * 86400:
                    raise HTTPException(409, "feedback_expired")
                row.useful, row.message, row.updated_at = body.useful, body.message, time.time()
            session.flush()
            return {"feedback": feedback_payload(row)}

    return router
