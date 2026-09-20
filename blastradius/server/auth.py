from __future__ import annotations

import hashlib
import secrets
import time

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from blastradius.server.config import Settings
from blastradius.server.events import record_event
from blastradius.server.models import LoginSession, Membership, Organization, User
from blastradius.server.schemas import email_identity

COOKIE = "br_session"


def oauth_client(settings: Settings) -> OAuth:
    oauth = OAuth()
    if settings.auth_mode == "oidc":
        oauth.register(
            name="oidc",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=settings.oidc_issuer.rstrip("/")
            + "/.well-known/openid-configuration",
            client_kwargs={
                "scope": "openid email profile",
                "code_challenge_method": "S256",
                "timeout": 10,
            },
        )
    return oauth


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_session(request: Request, db: Session) -> LoginSession | None:
    token = request.cookies.get(COOKIE, "")
    if len(token) > 100:
        return None
    session = db.get(LoginSession, token_hash(token)) if token else None
    if session and session.expires_at > time.time():
        return session
    return None


def create_session(
    response: Response,
    db: Session,
    settings: Settings,
    user_id: str | None = None,
    *,
    oidc_authenticated: bool = False,
) -> LoginSession:
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= time.time()))
    token = secrets.token_urlsafe(32)
    session = LoginSession(
        token_hash=token_hash(token),
        user_id=user_id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=time.time() + settings.session_ttl_seconds,
        oidc_authenticated=oidc_authenticated,
    )
    db.add(session)
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return session


def require_user(request: Request, db: Session, settings: Settings, mutation: bool = False) -> User:
    if settings.auth_mode == "disabled":
        raise HTTPException(503, "authentication_disabled")
    session = require_csrf(request, db, settings) if mutation else current_session(request, db)
    if not session or not session.user_id:
        raise HTTPException(401, "authentication_required")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "authentication_required")
    return user


def require_csrf(request: Request, db: Session, settings: Settings) -> LoginSession:
    origin = request.headers.get("origin")
    if origin and origin != settings.public_url.rstrip("/"):
        raise HTTPException(403, "invalid_origin")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "invalid_origin")
    session = current_session(request, db)
    provided = request.headers.get("x-csrf-token", "")
    if not session or not secrets.compare_digest(session.csrf_token.encode(), provided.encode()):
        raise HTTPException(403, "csrf_required")
    return session


def membership(
    db: Session, user: User, organization_id: str, roles: tuple[str, ...] = ()
) -> Membership:
    member = db.get(Membership, (user.id, organization_id))
    if not member:
        raise HTTPException(404, "not_found")
    if roles and member.role not in roles:
        raise HTTPException(403, "insufficient_role")
    return member


def provision(
    db: Session,
    issuer: str,
    subject: str,
    name: str,
    email: str,
    email_verified: bool = False,
) -> User:
    identity = email_identity(email) if email_verified else None
    user = db.scalar(select(User).where(User.issuer == issuer, User.subject == subject))
    if user:
        user.email = identity or ""
        user.email_verified = identity is not None
        user.name = name[:200]
        return user
    user = User(
        issuer=issuer,
        subject=subject,
        name=name[:200],
        email=identity or "",
        email_verified=identity is not None,
    )
    db.add(user)
    db.flush()
    org = Organization(name=(name[:70] or "Personal") + "'s workspace")
    db.add(org)
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role="owner"))
    record_event(db, "account_created", user_id=user.id)
    record_event(db, "workspace_created", user_id=user.id, organization_id=org.id)
    return user
