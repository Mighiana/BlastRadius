from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from blastradius.server.auth import (
    COOKIE,
    create_session,
    current_session,
    membership,
    oauth_client,
    provision,
    require_csrf,
    require_user,
)
from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.demos import build_demos
from blastradius.server.fixtures import FIXTURES
from blastradius.server.github_routes import github_router
from blastradius.server.github_service import GitHubService
from blastradius.server.jobs import JobManager
from blastradius.server.lease import ServiceLease
from blastradius.server.middleware import GuardMiddleware
from blastradius.server.models import Analysis, Membership, Organization, Project, User
from blastradius.server.plans import catalog, entitlements, require_feature
from blastradius.server.quotas import lock_org, quota, usage_payload, usage_row
from blastradius.server.lifecycle import authorized_org, lifecycle_router
from blastradius.server.persistence import effective_policy, visible_analysis, cutoff, public_result
from blastradius.server.schemas import (
    AnalysisInput,
    OrganizationInput,
    ProjectInput,
)
from blastradius.server.static import FrontendFiles, FrontendMount


def project_payload(project: Project) -> dict:
    return {
        "id": project.id,
        "organization_id": project.organization_id,
        "name": project.name,
        "description": project.description,
        "repository": project.repository,
        "repository_provider": project.repository_provider,
        "default_branch": project.default_branch,
        "environment": project.environment,
        "terraform_root": project.terraform_root,
        "archived_at": project.archived_at,
        "updated_at": project.updated_at,
        "created_at": project.created_at,
    }


def analysis_payload(job: Analysis, detail: bool = True, sarif: bool = False) -> dict:
    data = {
        "id": job.id,
        "project_id": job.project_id,
        "organization_id": job.organization_id,
        "base_label": job.base_label,
        "candidate_label": job.candidate_label,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "status": job.status,
        "error": job.error,
        "input_type": job.input_type,
        "base_ref": job.base_ref,
        "candidate_ref": job.candidate_ref,
        "base_sha": job.base_sha,
        "candidate_sha": job.candidate_sha,
        "decision": job.decision,
        "score_before": job.score_before,
        "score_after": job.score_after,
        "risk_before": job.risk_before,
        "risk_after": job.risk_after,
        "critical_paths_added": job.critical_paths_added,
        "critical_paths_removed": job.critical_paths_removed,
        "policy_snapshot": job.policy_snapshot,
        "normalized_version": job.normalized_version,
    }
    if detail:
        data["result"] = public_result(job.result, sarif)
    elif job.result:
        data["summary"] = {key: job.result[key] for key in ("decision", "score", "verdict")}
    return data


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    db = Database(settings)
    oauth = oauth_client(settings)
    jobs = JobManager(db, settings)
    github = GitHubService(db, settings, jobs)
    lease = ServiceLease(db, settings.data_dir)
    demos: dict[tuple[str, str], dict] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        lease.acquire()
        try:
            if settings.auto_migrate:
                db.migrate()
            if not db.ready():
                raise RuntimeError(
                    "Database schema is not ready; run python -m blastradius.server.migrate"
                )
            jobs.recover()
            github.recover()
            demos.update(await run_in_threadpool(build_demos, settings))
            yield
        finally:
            await run_in_threadpool(github.shutdown)
            await run_in_threadpool(jobs.shutdown)
            lease.release()
            db.engine.dispose()

    app = FastAPI(
        title="BlastRadius API",
        version="1",
        lifespan=lifespan,
        docs_url=None if settings.production else "/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.db, app.state.settings, app.state.jobs, app.state.oauth = (
        db,
        settings,
        jobs,
        oauth,
    )
    app.state.github = github
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="br_oidc",
        max_age=600,
        same_site="lax",
        https_only=settings.production,
    )
    if settings.production:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[urlsplit(settings.public_url).hostname or ""],
        )
    app.add_middleware(GuardMiddleware, settings=settings)
    app.include_router(lifecycle_router(db, settings))
    app.include_router(github_router(db, settings, github))

    @app.get("/api/plans")
    def plans():
        return catalog()

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        return JSONResponse({"detail": "invalid_request"}, status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, _error: Exception):
        return JSONResponse({"detail": "internal_error"}, status_code=500)

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        if not db.ready() or len(demos) != 9:
            raise HTTPException(503, "not_ready")
        return {"status": "ready"}

    @app.get("/api/me")
    def me(request: Request, response: Response):
        with db.session(write=True) as session:
            login = current_session(request, session) or create_session(response, session, settings)
            user = session.get(User, login.user_id) if login.user_id else None
            organizations = []
            if user:
                for org, member in session.execute(
                    select(Organization, Membership)
                    .join(Membership, Organization.id == Membership.organization_id)
                    .where(Membership.user_id == user.id)
                ):
                    organizations.append(
                        {
                            "id": org.id,
                            "name": org.name,
                            "role": member.role,
                            "plan": org.plan,
                            "usage": usage_payload(session, org),
                        }
                    )
            return {
                "authenticated": user is not None,
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "email": user.email,
                    "email_verified": user.email_verified,
                    "created_at": user.created_at,
                }
                if user
                else None,
                "organizations": organizations,
                "csrf_token": login.csrf_token,
                "auth": {
                    "enabled": settings.auth_mode != "disabled",
                    "mode": settings.auth_mode,
                    "public_url": settings.public_url.rstrip("/"),
                    "login_url": "/api/auth/login" if settings.auth_mode == "oidc" else None,
                },
                "billing": {"enabled": False, "mode": "commercial_beta"},
            }

    @app.post("/api/auth/demo")
    def demo_login(request: Request, response: Response):
        if settings.auth_mode != "demo" or settings.production:
            raise HTTPException(404, "demo_auth_disabled")
        with db.session(write=True) as session:
            old = require_csrf(request, session, settings)
            user = provision(
                session, "development-demo", secrets.token_urlsafe(24), "Local demo", ""
            )
            session.delete(old)
            create_session(response, session, settings, user.id)
        return {"authenticated": True}

    @app.get("/api/auth/login")
    async def login(request: Request):
        if settings.auth_mode != "oidc":
            raise HTTPException(503, "oidc_disabled")
        client = oauth.create_client("oidc")
        return await client.authorize_redirect(request, settings.public_url + "/api/auth/callback")

    @app.get("/api/auth/callback")
    async def callback(request: Request):
        if settings.auth_mode != "oidc":
            raise HTTPException(503, "oidc_disabled")
        try:
            client = oauth.create_client("oidc")
            state = await client.framework.get_state_data(
                request.session, request.query_params.get("state")
            )
            token = await client.authorize_access_token(request)
            claims = token.get("userinfo")
            if not claims or claims.get("iss") != settings.oidc_issuer or not claims.get("sub"):
                raise ValueError("Invalid identity")
            if not state or not state.get("nonce") or claims.get("nonce") != state["nonce"]:
                raise ValueError("Invalid nonce")
            subject = claims["sub"]
            if not isinstance(subject, str) or len(subject) > 255:
                raise ValueError("Invalid identity")
            response = RedirectResponse(settings.public_url + "/dashboard", status_code=303)
            with db.session(write=True) as session:
                user = provision(
                    session,
                    settings.oidc_issuer,
                    subject,
                    str(claims.get("name", "")),
                    str(claims.get("email", "")) if claims.get("email_verified") is True else "",
                    email_verified=claims.get("email_verified") is True,
                )
                old = current_session(request, session)
                if old:
                    session.delete(old)
                create_session(response, session, settings, user.id)
            return response
        except Exception:
            raise HTTPException(400, "authentication_failed") from None
        finally:
            request.session.clear()

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        with db.session(write=True) as session:
            session.delete(require_csrf(request, session, settings))
        response.delete_cookie(
            COOKIE, path="/", secure=settings.production, httponly=True, samesite="lax"
        )
        return {"authenticated": False}

    @app.get("/api/demo/scenarios")
    def scenarios():
        return {
            "scenarios": [
                {
                    "id": key,
                    "title": value["title"],
                    "root_cause": value["root_cause"],
                    "change": value["change"],
                    "stages": ["safe", "risky", "remediated"],
                }
                for key, value in FIXTURES.items()
            ]
        }

    @app.get("/api/demo/{scenario_id}")
    def demo(scenario_id: str, stage: Literal["safe", "risky", "remediated"] = "risky"):
        if (scenario_id, stage) not in demos:
            raise HTTPException(404, "not_found")
        return demos[(scenario_id, stage)]

    @app.post("/api/organizations", status_code=201)
    def create_organization(body: OrganizationInput, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            session.scalar(select(User).where(User.id == user.id).with_for_update())
            count = (
                session.scalar(
                    select(func.count())
                    .select_from(Membership)
                    .where(Membership.user_id == user.id, Membership.role == "owner")
                )
                or 0
            )
            if count >= 5:
                raise HTTPException(402, "organization_limit_exceeded")
            org = Organization(name=body.name)
            session.add(org)
            session.flush()
            session.add(Membership(user_id=user.id, organization_id=org.id, role="owner"))
            return {"id": org.id, "name": org.name, "role": "owner", "plan": org.plan}

    @app.get("/api/projects")
    def projects(
        request: Request,
        organization_id: str | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        with db.session() as session:
            user = require_user(request, session, settings)
            query = (
                select(Project)
                .join(Membership, Membership.organization_id == Project.organization_id)
                .where(Membership.user_id == user.id)
            )
            if organization_id:
                membership(session, user, organization_id)
                query = query.where(Project.organization_id == organization_id)
            return {
                "projects": [
                    project_payload(project)
                    for project in session.scalars(
                        query.order_by(Project.created_at.desc(), Project.id)
                        .limit(limit)
                        .offset(offset)
                    )
                ]
            }

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectInput, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            org = authorized_org(session, user, body.organization_id, ("owner", "admin"))
            quota(session, org, "projects")
            project = Project(**body.model_dump())
            session.add(project)
            session.flush()
            return project_payload(project)

    @app.get("/api/projects/{project_id}")
    def project_detail(project_id: str, request: Request):
        with db.session() as session:
            user = require_user(request, session, settings)
            project = session.get(Project, project_id)
            if project is None:
                raise HTTPException(404, "not_found")
            membership(session, user, project.organization_id)
            return project_payload(project)

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(project_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            project = session.get(Project, project_id)
            if not project:
                raise HTTPException(404, "not_found")
            authorized_org(session, user, project.organization_id, ("owner", "admin"))
            session.delete(project)

    @app.get("/api/projects/{project_id}/analyses")
    def history(
        project_id: str,
        request: Request,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        status: Literal["queued", "running", "succeeded", "failed"] | None = None,
        decision: str | None = None,
        input_type: Literal["hcl", "plan", "github"] | None = None,
        branch: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ):
        with db.session() as session:
            user = require_user(request, session, settings)
            project = session.get(Project, project_id)
            if not project:
                raise HTTPException(404, "not_found")
            membership(session, user, project.organization_id)
            org = session.get(Organization, project.organization_id)
            assert org is not None
            query = select(Analysis).where(
                Analysis.project_id == project_id, Analysis.created_at > cutoff(org)
            )
            if status:
                query = query.where(Analysis.status == status)
            if decision:
                query = query.where(Analysis.decision == decision)
            if input_type:
                query = query.where(Analysis.input_type == input_type)
            if branch:
                query = query.where(Analysis.candidate_ref == branch)
            if since is not None:
                query = query.where(Analysis.created_at >= since)
            if until is not None:
                query = query.where(Analysis.created_at <= until)
            return {
                "total": session.scalar(select(func.count()).select_from(query.subquery())),
                "limit": limit,
                "offset": offset,
                "analyses": [
                    analysis_payload(job, False)
                    for job in session.scalars(
                        query.order_by(Analysis.created_at.desc(), Analysis.id)
                        .limit(limit)
                        .offset(offset)
                    )
                ],
            }

    @app.post("/api/analyses", status_code=202)
    def create_analysis(body: AnalysisInput, request: Request):
        if any(
            len(files or {}) > settings.max_files for files in (body.before_files, body.after_files)
        ):
            raise HTTPException(413, "file_limit_exceeded")
        reserved = False
        try:
            with db.session(write=True) as session:
                user = require_user(request, session, settings, True)
                project = session.get(Project, body.project_id)
                if not project:
                    raise HTTPException(404, "not_found")
                org = authorized_org(
                    session, user, project.organization_id, ("owner", "admin", "developer")
                )
                session.refresh(project)
                if project.archived_at is not None:
                    raise HTTPException(409, "project_archived")
                if not jobs.reserve():
                    raise HTTPException(429, "job_capacity_exceeded")
                reserved = True
                quota(session, org, "analyses_per_month")
                job = Analysis(
                    project_id=project.id,
                    organization_id=org.id,
                    created_by=user.id,
                    base_label=body.base_label,
                    candidate_label=body.candidate_label,
                    input_type="plan" if body.plan is not None else "hcl",
                    base_ref=body.base_ref,
                    candidate_ref=body.candidate_ref,
                    base_sha=body.base_sha,
                    candidate_sha=body.candidate_sha,
                    policy_snapshot=effective_policy(org, project),
                    request_id=request.state.request_id,
                )
                session.add(job)
                session.flush()
                data = analysis_payload(job)
            jobs.submit(job.id, body)
            return data
        except BaseException:
            if reserved:
                jobs.slots.release()
            raise

    @app.get("/api/analyses/{analysis_id}")
    def analysis(analysis_id: str, request: Request):
        with db.session() as session:
            user = require_user(request, session, settings)
            job, org = visible_analysis(session, user, analysis_id)
            return analysis_payload(job, sarif=entitlements(org).sarif)

    @app.delete("/api/analyses/{analysis_id}", status_code=204)
    def delete_analysis(analysis_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            job = session.get(Analysis, analysis_id)
            if not job:
                raise HTTPException(404, "not_found")
            authorized_org(session, user, job.organization_id, ("owner", "admin", "developer"))
            session.delete(job)

    @app.get("/api/analyses/{analysis_id}/report")
    def report(
        analysis_id: str,
        request: Request,
        format: Literal["json", "markdown", "sarif", "web"] = "web",
    ):
        with db.session(write=True) as session:
            user = require_user(request, session, settings)
            job, org = visible_analysis(session, user, analysis_id)
            org = lock_org(session, org.id)
            job, org = visible_analysis(session, user, analysis_id)
            if job.status != "succeeded" or not job.result:
                raise HTTPException(409, "report_not_ready")
            if format == "sarif":
                require_feature(org, "sarif")
            if format != "web":
                usage_row(session, org).exports += 1
            result = public_result(job.result, entitlements(org).sarif)
            assert result is not None
            if format == "markdown":
                return Response(
                    result["reports"]["markdown"],
                    media_type="text/markdown",
                    headers={"Content-Disposition": 'attachment; filename="report.md"'},
                )
            if format == "sarif":
                return JSONResponse(
                    result["reports"]["sarif"],
                    headers={"Content-Disposition": 'attachment; filename="report.sarif"'},
                )
            return JSONResponse(
                result,
                headers={"Content-Disposition": 'attachment; filename="report.json"'}
                if format == "json"
                else {},
            )

    @app.get("/api/organizations/{organization_id}/billing")
    def billing_status(organization_id: str, request: Request):
        with db.session() as session:
            user = require_user(request, session, settings)
            membership(session, user, organization_id, ("owner",))
            org = lock_org(session, organization_id)
            return {
                "enabled": settings.billing_enabled,
                "mode": "commercial_beta",
                "plan": org.plan,
                "usage": usage_payload(session, org),
            }

    if (settings.static_dir / "index.html").is_file():
        app.router.routes.append(
            FrontendMount("/", app=FrontendFiles(directory=settings.static_dir), name="frontend")
        )

    return app


app = create_app()
