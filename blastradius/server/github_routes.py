from __future__ import annotations

import hashlib
import hmac
import json
import re
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from blastradius.server.auth import membership, require_user
from blastradius.server.config import Settings
from blastradius.server.events import record_event
from blastradius.server.db import Database
from blastradius.server.github_api import GitHubAPI, GitHubError
from blastradius.server.github_service import GitHubService
from blastradius.server.github_types import ConnectionInput, LifecycleEvent, PullEvent
from blastradius.server.lifecycle import authorized_org
from blastradius.server.models import GitHubInstallation, GitHubRun, Project, RepositoryConnection
from blastradius.server.persistence import audit, cutoff
from blastradius.server.quotas import lock_org


def register_installation(
    db: Database,
    settings: Settings,
    organization_id: str,
    installation_id: int,
    account_id: int,
    verification_reference: str,
) -> dict:
    if not settings.admin_enabled or not settings.github_enabled:
        raise ValueError("GitHub registration requires configured App and BR_ADMIN_ENABLED=true")
    if (
        not 0 < installation_id <= 9223372036854775807
        or not 0 < account_id <= 9223372036854775807
        or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", verification_reference)
    ):
        raise ValueError("invalid registration identifiers or verification reference")
    with GitHubAPI(settings) as api:
        record = api.installation(installation_id, account_id)
    with db.session(write=True) as session:
        org = lock_org(session, organization_id)
        installation = session.get(GitHubInstallation, installation_id)
        if installation and (
            installation.organization_id != org.id or installation.account_id != account_id
        ):
            raise ValueError("installation already registered to another workspace/account")
        if not installation:
            installation = GitHubInstallation(
                id=record.id,
                organization_id=org.id,
                account_id=record.account.id,
                account_login=record.account.login,
            )
            session.add(installation)
        installation.status, installation.verified_at = "active", time.time()
        audit(
            session,
            org.id,
            "operator",
            "github.installation_registered",
            str(record.id),
            {"verification_reference": verification_reference, "account_id": account_id},
        )
    return {
        "installation_id": installation_id,
        "organization_id": organization_id,
        "status": "active",
    }


def connection_payload(connection: RepositoryConnection) -> dict:
    return {
        "id": connection.id,
        "installation_id": connection.installation_id,
        "repository_id": connection.repository_id,
        "full_name": connection.full_name,
        "status": connection.status,
        "created_at": connection.created_at,
    }


def github_router(db: Database, settings: Settings, service: GitHubService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/github/config")
    def configuration():
        available = False
        if settings.github_enabled:
            try:
                with service.api_factory() as api:
                    api.app_token()
                available = True
            except GitHubError:
                pass
        return {
            "configured": settings.github_enabled,
            "available": available,
            "mode": "operator_registration",
            "self_service": False,
            "app_slug": settings.github_app_slug or None,
            "installation_url": (
                f"https://github.com/apps/{settings.github_app_slug}/installations/new"
                if available
                else None
            ),
            "reason": "operator_registration_required" if available else "github_not_configured",
            "permissions": {
                "contents": "read",
                "pull_requests": "write",
                "checks": "write",
                "metadata": "read",
            },
        }

    @router.get("/api/organizations/{organization_id}/github/installations")
    def installations(organization_id: str, request: Request):
        with db.session() as session:
            user = require_user(request, session, settings)
            membership(session, user, organization_id)
            return {
                "installations": [
                    {
                        "id": item.id,
                        "account_id": item.account_id,
                        "account_login": item.account_login,
                        "status": item.status,
                        "verified_at": item.verified_at,
                    }
                    for item in session.scalars(
                        select(GitHubInstallation)
                        .where(GitHubInstallation.organization_id == organization_id)
                        .order_by(GitHubInstallation.id)
                        .limit(100)
                    )
                ]
            }

    @router.get("/api/projects/{project_id}/github")
    def status(project_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings)
            project = session.get(Project, project_id)
            if not project:
                raise HTTPException(404, "not_found")
            org = authorized_org(session, user, project.organization_id)
            connection = session.scalar(
                select(RepositoryConnection).where(RepositoryConnection.project_id == project_id)
            )
            run = (
                session.scalar(
                    select(GitHubRun)
                    .where(
                        GitHubRun.connection_id == connection.id,
                        GitHubRun.created_at > cutoff(org),
                    )
                    .order_by(GitHubRun.created_at.desc())
                    .limit(1)
                )
                if connection
                else None
            )
            return {
                "connection": connection_payload(connection) if connection else None,
                "latest_run": {
                    "id": run.id,
                    "analysis_id": run.analysis_id,
                    "pull_number": run.pull_number,
                    "base_sha": run.base_sha,
                    "head_sha": run.head_sha,
                    "base_ref": run.base_ref,
                    "head_ref": run.head_ref,
                    "head_repository_id": run.head_repository_id,
                    "status": run.status,
                    "error": run.error,
                    "check_id": run.check_id,
                }
                if run
                else None,
            }

    @router.put("/api/projects/{project_id}/github")
    def connect(project_id: str, body: ConnectionInput, request: Request):
        if not settings.github_enabled:
            raise HTTPException(503, "github_not_configured")
        with db.session(write=True) as session:
            user = require_user(request, session, settings, mutation=True)
            project = session.get(Project, project_id)
            if not project:
                raise HTTPException(404, "not_found")
            authorized_org(session, user, project.organization_id, ("owner", "admin"))
            installation = session.get(GitHubInstallation, body.installation_id)
            if not installation or installation.organization_id != project.organization_id:
                raise HTTPException(404, "not_found")
            if installation.status != "active" or project.archived_at is not None:
                raise HTTPException(409, "github_connection_unavailable")
            account_id = installation.account_id
        try:
            with service.api_factory() as api:
                api.installation(body.installation_id, account_id)
                token = api.installation_token(body.installation_id, body.repository_id)
                repo = api.repository(token, body.repository_id, account_id)
        except GitHubError:
            raise HTTPException(409, "github_repository_unavailable") from None
        try:
            with db.session(write=True) as session:
                user = require_user(request, session, settings, mutation=True)
                project = session.get(Project, project_id)
                if not project:
                    raise HTTPException(404, "not_found")
                authorized_org(session, user, project.organization_id, ("owner", "admin"))
                installation = session.get(GitHubInstallation, body.installation_id)
                if (
                    not installation
                    or installation.organization_id != project.organization_id
                    or installation.status != "active"
                    or project.archived_at is not None
                ):
                    raise HTTPException(409, "github_connection_unavailable")
                connection = session.scalar(
                    select(RepositoryConnection).where(
                        RepositoryConnection.project_id == project_id
                    )
                )
                if connection and (
                    connection.repository_id != repo.id
                    or connection.installation_id != installation.id
                ):
                    raise HTTPException(409, "github_project_already_connected")
                if not connection:
                    connection = RepositoryConnection(
                        installation_id=installation.id,
                        repository_id=repo.id,
                        project_id=project_id,
                        full_name=repo.full_name,
                        created_by=user.id,
                    )
                    session.add(connection)
                    record_event(
                        session,
                        "github_connected",
                        user_id=user.id,
                        organization_id=project.organization_id,
                        project_id=project.id,
                    )
                elif connection.status != "active":
                    record_event(
                        session,
                        "github_connected",
                        user_id=user.id,
                        organization_id=project.organization_id,
                        project_id=project.id,
                    )
                connection.full_name, connection.status = repo.full_name, "active"
                project.repository, project.repository_provider = repo.full_name, "github"
                project.default_branch, project.updated_at = repo.default_branch, time.time()
                session.flush()
                audit(session, project.organization_id, user.id, "github.connected", connection.id)
                return connection_payload(connection)
        except IntegrityError:
            raise HTTPException(409, "github_repository_already_connected") from None

    @router.delete("/api/projects/{project_id}/github", status_code=204)
    def disconnect(project_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, mutation=True)
            project = session.get(Project, project_id)
            if not project:
                raise HTTPException(404, "not_found")
            authorized_org(session, user, project.organization_id, ("owner", "admin"))
            connection = session.scalar(
                select(RepositoryConnection).where(RepositoryConnection.project_id == project_id)
            )
            if connection:
                connection.status = "disconnected"
                audit(
                    session, project.organization_id, user.id, "github.disconnected", connection.id
                )

    @router.post("/api/github/webhook", status_code=202)
    async def webhook(request: Request):
        if not settings.github_enabled:
            raise HTTPException(503, "github_not_configured")
        raw = await request.body()
        signature = request.headers.get("x-hub-signature-256", "")
        expected = (
            "sha256="
            + hmac.new(settings.github_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(signature.encode(), expected.encode()):
            raise HTTPException(401, "github_signature_invalid")
        delivery_id = request.headers.get("x-github-delivery", "")
        event = request.headers.get("x-github-event", "")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", delivery_id) or not re.fullmatch(
            r"[a-z_]{1,40}", event
        ):
            raise HTTPException(400, "github_headers_invalid")
        payload: PullEvent | LifecycleEvent | None = None
        try:
            if event == "pull_request":
                obj = json.loads(raw)
                if not isinstance(obj, dict):
                    raise ValueError
                if obj.get("action") in ("opened", "synchronize", "reopened", "edited"):
                    payload = PullEvent.model_validate(obj)
            elif event in ("installation", "installation_repositories"):
                payload = LifecycleEvent.model_validate_json(raw)
        except (ValueError, ValidationError, RecursionError):
            raise HTTPException(400, "github_payload_invalid") from None
        digest = hashlib.sha256(event.encode() + b"\0" + raw).hexdigest()
        return await run_in_threadpool(service.accept, delivery_id, digest, event, payload)

    return router
