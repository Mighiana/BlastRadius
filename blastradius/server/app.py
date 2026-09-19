from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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
from blastradius.server.billing import (
    Gateway,
    StripeGateway,
    apply_event,
    verified_event,
)
from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.demos import build_demos
from blastradius.server.fixtures import FIXTURES
from blastradius.server.jobs import JobManager
from blastradius.server.lease import ServiceLease
from blastradius.server.middleware import GuardMiddleware
from blastradius.server.models import Analysis, Membership, Organization, Project, User
from blastradius.server.quotas import lock_org, quota, usage_payload
from blastradius.server.schemas import (
    AnalysisInput,
    CheckoutInput,
    MemberInput,
    OrganizationInput,
    ProjectInput,
)
from blastradius.server.static import FrontendFiles


def project_payload(project: Project) -> dict:
    return {
        "id": project.id,
        "organization_id": project.organization_id,
        "name": project.name,
        "created_at": project.created_at,
    }


def analysis_payload(job: Analysis, detail: bool = True) -> dict:
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
    }
    if detail:
        data["result"] = job.result
    elif job.result:
        data["summary"] = {
            key: job.result[key] for key in ("decision", "score", "verdict")
        }
    return data


def create_app(
    settings: Settings | None = None, *, gateway: Gateway | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    db = Database(settings)
    oauth = oauth_client(settings)
    jobs = JobManager(db, settings)
    lease = ServiceLease(db, settings.data_dir)
    billing = gateway or (StripeGateway(settings) if settings.billing_enabled else None)
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
            demos.update(await run_in_threadpool(build_demos, settings))
            yield
        finally:
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
            login = current_session(request, session) or create_session(
                response, session, settings
            )
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
                "user": {"id": user.id, "name": user.name, "email": user.email}
                if user
                else None,
                "organizations": organizations,
                "csrf_token": login.csrf_token,
                "auth": {
                    "enabled": settings.auth_mode != "disabled",
                    "mode": settings.auth_mode,
                    "public_url": settings.public_url.rstrip("/"),
                    "login_url": "/api/auth/login"
                    if settings.auth_mode == "oidc"
                    else None,
                },
                "billing": {"enabled": settings.billing_enabled, "test_mode": True},
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
        return await client.authorize_redirect(
            request, settings.public_url + "/api/auth/callback"
        )

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
            if (
                not claims
                or claims.get("iss") != settings.oidc_issuer
                or not claims.get("sub")
            ):
                raise ValueError("Invalid identity")
            if (
                not state
                or not state.get("nonce")
                or claims.get("nonce") != state["nonce"]
            ):
                raise ValueError("Invalid nonce")
            subject = claims["sub"]
            if not isinstance(subject, str) or len(subject) > 255:
                raise ValueError("Invalid identity")
            response = RedirectResponse(
                settings.public_url + "/dashboard", status_code=303
            )
            with db.session(write=True) as session:
                user = provision(
                    session,
                    settings.oidc_issuer,
                    subject,
                    str(claims.get("name", "")),
                    str(claims.get("email", ""))
                    if claims.get("email_verified") is True
                    else "",
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
            session.add(
                Membership(user_id=user.id, organization_id=org.id, role="owner")
            )
            return {"id": org.id, "name": org.name, "role": "owner", "plan": org.plan}

    @app.get("/api/organizations/{organization_id}/members")
    def members(organization_id: str, request: Request):
        with db.session() as session:
            user = require_user(request, session, settings)
            membership(session, user, organization_id, ("owner",))
            return {
                "members": [
                    {"user_id": member.user_id, "role": member.role}
                    for member in session.scalars(
                        select(Membership).where(
                            Membership.organization_id == organization_id
                        )
                    )
                ]
            }

    @app.post("/api/organizations/{organization_id}/members", status_code=201)
    def add_member(organization_id: str, body: MemberInput, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            membership(session, user, organization_id, ("owner",))
            org = lock_org(session, organization_id)
            if not session.get(User, body.user_id):
                raise HTTPException(404, "user_not_found")
            if session.get(Membership, (body.user_id, organization_id)):
                raise HTTPException(409, "already_member")
            quota(session, org, "members")
            session.add(
                Membership(
                    user_id=body.user_id,
                    organization_id=organization_id,
                    role=body.role,
                )
            )
            return {"user_id": body.user_id, "role": body.role}

    @app.delete(
        "/api/organizations/{organization_id}/members/{user_id}", status_code=204
    )
    def remove_member(organization_id: str, user_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            membership(session, user, organization_id, ("owner",))
            member = session.get(Membership, (user_id, organization_id))
            if not member:
                raise HTTPException(404, "not_found")
            if member.role == "owner":
                raise HTTPException(409, "cannot_remove_owner")
            session.delete(member)

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
            membership(session, user, body.organization_id, ("owner", "member"))
            quota(session, lock_org(session, body.organization_id), "projects")
            project = Project(organization_id=body.organization_id, name=body.name)
            session.add(project)
            session.flush()
            return project_payload(project)

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(project_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            project = session.get(Project, project_id)
            if not project:
                raise HTTPException(404, "not_found")
            membership(session, user, project.organization_id, ("owner",))
            session.delete(project)

    @app.get("/api/projects/{project_id}/analyses")
    def history(
        project_id: str,
        request: Request,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        with db.session() as session:
            user = require_user(request, session, settings)
            project = session.get(Project, project_id)
            if not project:
                raise HTTPException(404, "not_found")
            membership(session, user, project.organization_id)
            return {
                "analyses": [
                    analysis_payload(job, False)
                    for job in session.scalars(
                        select(Analysis)
                        .where(Analysis.project_id == project_id)
                        .order_by(Analysis.created_at.desc(), Analysis.id)
                        .limit(limit)
                        .offset(offset)
                    )
                ]
            }

    @app.post("/api/analyses", status_code=202)
    def create_analysis(body: AnalysisInput, request: Request):
        if any(
            len(files or {}) > settings.max_files
            for files in (body.before_files, body.after_files)
        ):
            raise HTTPException(413, "file_limit_exceeded")
        reserved = False
        try:
            with db.session(write=True) as session:
                user = require_user(request, session, settings, True)
                project = session.get(Project, body.project_id)
                if not project:
                    raise HTTPException(404, "not_found")
                membership(session, user, project.organization_id, ("owner", "member"))
                org = lock_org(session, project.organization_id)
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
            job = session.get(Analysis, analysis_id)
            if not job:
                raise HTTPException(404, "not_found")
            membership(session, user, job.organization_id)
            return analysis_payload(job)

    @app.delete("/api/analyses/{analysis_id}", status_code=204)
    def delete_analysis(analysis_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            job = session.get(Analysis, analysis_id)
            if not job:
                raise HTTPException(404, "not_found")
            membership(session, user, job.organization_id, ("owner", "member"))
            session.delete(job)

    @app.get("/api/analyses/{analysis_id}/report")
    def report(
        analysis_id: str,
        request: Request,
        format: Literal["json", "markdown", "sarif", "web"] = "web",
    ):
        with db.session() as session:
            user = require_user(request, session, settings)
            job = session.get(Analysis, analysis_id)
            if not job:
                raise HTTPException(404, "not_found")
            membership(session, user, job.organization_id)
            if job.status != "succeeded" or not job.result:
                raise HTTPException(409, "report_not_ready")
            result = job.result
            if format == "markdown":
                return Response(
                    result["reports"]["markdown"],
                    media_type="text/markdown",
                    headers={"Content-Disposition": 'attachment; filename="report.md"'},
                )
            if format == "sarif":
                return JSONResponse(
                    result["reports"]["sarif"],
                    headers={
                        "Content-Disposition": 'attachment; filename="report.sarif"'
                    },
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
                "test_mode": True,
                "plan": org.plan,
                "subscription_status": org.subscription_status,
                "usage": usage_payload(session, org),
            }

    @app.post("/api/organizations/{organization_id}/billing/checkout")
    def checkout(organization_id: str, body: CheckoutInput, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            membership(session, user, organization_id, ("owner",))
            org = lock_org(session, organization_id)
            if not billing:
                raise HTTPException(503, "billing_disabled")
            if org.subscription_status in {
                "active",
                "trialing",
                "past_due",
                "unpaid",
                "paused",
            }:
                raise HTTPException(409, "use_billing_portal")
            try:
                if not org.customer_id:
                    org.customer_id = billing.customer(org.id)
                price = (
                    settings.stripe_price_pro
                    if body.plan == "pro"
                    else settings.stripe_price_team
                )
                return {
                    "url": billing.checkout(
                        org.customer_id, price, settings.public_url + "/billing"
                    )
                }
            except Exception:
                raise HTTPException(502, "billing_provider_unavailable") from None

    @app.post("/api/organizations/{organization_id}/billing/portal")
    def portal(organization_id: str, request: Request):
        with db.session() as session:
            user = require_user(request, session, settings, True)
            membership(session, user, organization_id, ("owner",))
            org = lock_org(session, organization_id)
            if not billing:
                raise HTTPException(503, "billing_disabled")
            if not org.customer_id:
                raise HTTPException(409, "billing_customer_missing")
            try:
                return {
                    "url": billing.portal(
                        org.customer_id, settings.public_url + "/billing"
                    )
                }
            except Exception:
                raise HTTPException(502, "billing_provider_unavailable") from None

    @app.post("/api/billing/webhook")
    async def webhook(request: Request):
        event = verified_event(
            await request.body(), request.headers.get("stripe-signature", ""), settings
        )
        try:
            with db.session(write=True) as session:
                return apply_event(session, event, settings)
        except IntegrityError:
            return {"received": True, "duplicate": True}

    if (settings.static_dir / "index.html").is_file():
        app.mount("/", FrontendFiles(directory=settings.static_dir), name="frontend")

    return app


app = create_app()
