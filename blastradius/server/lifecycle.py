import json
import secrets
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from blastradius.server.auth import (
    current_session,
    membership,
    require_user,
    token_hash,
)
from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.models import (
    AnalysisArtifact,
    AttackPath,
    AttackPathHop,
    AuditEvent,
    Finding,
    Invitation,
    LoginSession,
    Membership,
    Organization,
    Project,
    User,
)
from blastradius.server.persistence import audit, effective_policy, public_result, visible_analysis
from blastradius.server.plans import entitlements, require_feature
from blastradius.server.quotas import counts, lock_org, quota, usage_payload, usage_row
from blastradius.server.schemas import (
    AcceptInvitation,
    InvitationInput,
    OrganizationInput,
    PolicyInput,
    ProjectUpdate,
    RoleInput,
)

MANAGERS = ("owner", "admin")


def authorized_org(
    session: Session,
    user: User,
    org_id: str,
    roles: tuple[str, ...] = (),
) -> Organization:
    membership(session, user, org_id, roles)
    org = lock_org(session, org_id)
    session.expire_all()
    membership(session, user, org_id, roles)
    return org


def member_target(
    session: Session,
    actor: User,
    org_id: str,
    target_id: str,
    new_role: str | None = None,
) -> Membership:
    org = authorized_org(session, actor, org_id, MANAGERS)
    actor_role = membership(session, actor, org_id).role
    target = session.get(Membership, (target_id, org_id))
    if target is None:
        raise HTTPException(404, "not_found")
    if (target.role == "owner" or new_role == "owner") and actor_role != "owner":
        raise HTTPException(403, "insufficient_role")
    if new_role:
        require_feature(org, "team")
    if target.role == "owner" and new_role != "owner":
        owners = (
            session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.organization_id == org_id, Membership.role == "owner")
            )
            or 0
        )
        if owners <= 1:
            raise HTTPException(409, "last_owner")
    return target


def invitation_payload(invite: Invitation) -> dict:
    return {
        "id": invite.id,
        "organization_id": invite.organization_id,
        "email": invite.email,
        "role": invite.role,
        "created_at": invite.created_at,
        "expires_at": invite.expires_at,
        "revoked_at": invite.revoked_at,
        "accepted_at": invite.accepted_at,
    }


def lifecycle_router(db: Database, settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/api/account/sessions")
    def sessions(request: Request):
        with db.session() as session:
            user = require_user(request, session, settings)
            current = current_session(request, session)
            return {
                "sessions": [
                    {
                        "id": row.id,
                        "created_at": row.created_at,
                        "expires_at": row.expires_at,
                        "current": current is not None and row.token_hash == current.token_hash,
                    }
                    for row in session.scalars(
                        select(LoginSession).where(
                            LoginSession.user_id == user.id, LoginSession.expires_at > time.time()
                        )
                    )
                ]
            }

    @router.delete("/api/account/sessions/{session_id}", status_code=204)
    def revoke_session(session_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            row = session.scalar(
                select(LoginSession).where(
                    LoginSession.id == session_id, LoginSession.user_id == user.id
                )
            )
            if row is None:
                raise HTTPException(404, "not_found")
            session.delete(row)

    @router.delete("/api/account/sessions", status_code=204)
    def revoke_sessions(request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))

    @router.patch("/api/organizations/{organization_id}")
    def update_organization(organization_id: str, body: OrganizationInput, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            org = authorized_org(session, user, organization_id, MANAGERS)
            org.name, org.updated_at = body.name, time.time()
            audit(session, org.id, user.id, "organization.updated", org.id)
            return {"id": org.id, "name": org.name, "plan": org.plan}

    @router.delete("/api/organizations/{organization_id}", status_code=204)
    def delete_organization(organization_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            org = authorized_org(session, user, organization_id, ("owner",))
            audit(session, None, user.id, "organization.deleted", org.id)
            session.delete(org)

    @router.get("/api/organizations/{organization_id}/usage")
    def usage(organization_id: str, request: Request):
        with db.session() as session:
            user = require_user(request, session, settings)
            membership(session, user, organization_id)
            org = session.get(Organization, organization_id)
            assert org is not None
            return usage_payload(session, org)

    @router.get("/api/organizations/{organization_id}/members")
    def members(organization_id: str, request: Request):
        with db.session() as session:
            user = require_user(request, session, settings)
            membership(session, user, organization_id, MANAGERS)
            return {
                "members": [
                    {
                        "user_id": row.user_id,
                        "role": row.role,
                        "name": account.name,
                        "email": account.email,
                    }
                    for row, account in session.execute(
                        select(Membership, User)
                        .join(User, User.id == Membership.user_id)
                        .where(Membership.organization_id == organization_id)
                    )
                ]
            }

    @router.patch("/api/organizations/{organization_id}/members/{user_id}")
    def update_member(organization_id: str, user_id: str, body: RoleInput, request: Request):
        with db.session(write=True) as session:
            actor = require_user(request, session, settings, True)
            target = member_target(session, actor, organization_id, user_id, body.role)
            target.role = body.role
            audit(
                session,
                organization_id,
                actor.id,
                "member.role_changed",
                user_id,
                {"role": body.role},
            )
            return {"user_id": user_id, "role": body.role}

    @router.delete("/api/organizations/{organization_id}/members/{user_id}", status_code=204)
    def remove_member(organization_id: str, user_id: str, request: Request):
        with db.session(write=True) as session:
            actor = require_user(request, session, settings, True)
            target = member_target(session, actor, organization_id, user_id)
            session.delete(target)
            audit(session, organization_id, actor.id, "member.removed", user_id)

    @router.post("/api/organizations/{organization_id}/invitations", status_code=201)
    def invite(organization_id: str, body: InvitationInput, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            org = authorized_org(session, user, organization_id, MANAGERS)
            require_feature(org, "team")
            quota(session, org, "members")
            token = secrets.token_urlsafe(32)
            row = Invitation(
                organization_id=org.id,
                email=body.email,
                role=body.role,
                token_hash=token_hash(token),
                created_by=user.id,
                expires_at=time.time() + 7 * 86400,
            )
            session.add(row)
            session.flush()
            audit(session, org.id, user.id, "invitation.created", row.id, {"role": row.role})
            return {
                **invitation_payload(row),
                "invitation_url": settings.public_url.rstrip("/")
                + "/invitations/accept#token="
                + token,
                "delivery": "manual",
            }

    @router.get("/api/organizations/{organization_id}/invitations")
    def invitations(
        organization_id: str,
        request: Request,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        with db.session() as session:
            user = require_user(request, session, settings)
            membership(session, user, organization_id, MANAGERS)
            return {
                "invitations": [
                    invitation_payload(row)
                    for row in session.scalars(
                        select(Invitation)
                        .where(Invitation.organization_id == organization_id)
                        .order_by(Invitation.created_at.desc(), Invitation.id)
                        .limit(limit)
                        .offset(offset)
                    )
                ]
            }

    @router.delete(
        "/api/organizations/{organization_id}/invitations/{invitation_id}", status_code=204
    )
    def revoke_invite(organization_id: str, invitation_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            authorized_org(session, user, organization_id, MANAGERS)
            row = session.get(Invitation, invitation_id)
            if row is None or row.organization_id != organization_id:
                raise HTTPException(404, "not_found")
            row.revoked_at = time.time()
            audit(session, organization_id, user.id, "invitation.revoked", row.id)

    @router.post("/api/invitations/accept")
    def accept_invite(body: AcceptInvitation, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            invite = session.scalar(
                select(Invitation).where(Invitation.token_hash == token_hash(body.token))
            )
            if invite is None:
                raise HTTPException(404, "invitation_unavailable")
            org = lock_org(session, invite.organization_id)
            session.refresh(invite)
            if (
                invite.revoked_at is not None
                or invite.accepted_at is not None
                or invite.expires_at <= time.time()
                or not user.email_verified
                or user.issuer == "development-demo"
                or not user.email
                or user.email.casefold() != invite.email
            ):
                raise HTTPException(404, "invitation_unavailable")
            require_feature(org, "team")
            if session.get(Membership, (user.id, org.id)) is not None:
                raise HTTPException(404, "invitation_unavailable")
            current = counts(session, org)
            if current["members"] + current["pending_invitations"] > entitlements(org).members:
                raise HTTPException(402, "members_quota_exceeded")
            invite.accepted_at = time.time()
            session.add(Membership(user_id=user.id, organization_id=org.id, role=invite.role))
            audit(session, org.id, user.id, "invitation.accepted", invite.id)
            return {"organization_id": org.id, "role": invite.role}

    @router.patch("/api/projects/{project_id}")
    def update_project(project_id: str, body: ProjectUpdate, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            project = session.get(Project, project_id)
            if project is None:
                raise HTTPException(404, "not_found")
            org = authorized_org(session, user, project.organization_id, MANAGERS)
            if not body.archived and project.archived_at is not None:
                quota(session, org, "projects")
            project.name, project.description = body.name, body.description
            project.repository, project.default_branch = body.repository, body.default_branch
            project.repository_provider = body.repository_provider
            project.environment, project.terraform_root = body.environment, body.terraform_root
            project.archived_at = (project.archived_at or time.time()) if body.archived else None
            project.updated_at = time.time()
            audit(
                session, org.id, user.id, "project.updated", project.id, {"archived": body.archived}
            )
            return {"id": project.id, **body.model_dump(), "archived_at": project.archived_at}

    @router.get("/api/projects/{project_id}/policy")
    def project_policy(project_id: str, request: Request):
        with db.session() as session:
            user = require_user(request, session, settings)
            project = session.get(Project, project_id)
            if project is None:
                raise HTTPException(404, "not_found")
            membership(session, user, project.organization_id)
            org = session.get(Organization, project.organization_id)
            assert org is not None
            return {
                "policy": project.policy,
                "version": project.policy_version,
                "effective": effective_policy(org, project),
            }

    @router.put("/api/projects/{project_id}/policy")
    def set_project_policy(project_id: str, body: PolicyInput, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            project = session.get(Project, project_id)
            if project is None:
                raise HTTPException(404, "not_found")
            org = authorized_org(session, user, project.organization_id, MANAGERS)
            require_feature(org, "advanced_policy")
            project.policy, project.policy_version = body.model_dump(), project.policy_version + 1
            audit(
                session,
                org.id,
                user.id,
                "project.policy_updated",
                project.id,
                {"version": project.policy_version},
            )
            return {"policy": project.policy, "version": project.policy_version}

    @router.delete("/api/projects/{project_id}/policy", status_code=204)
    def clear_project_policy(project_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            project = session.get(Project, project_id)
            if project is None:
                raise HTTPException(404, "not_found")
            authorized_org(session, user, project.organization_id, MANAGERS)
            project.policy, project.policy_version = None, project.policy_version + 1
            audit(session, project.organization_id, user.id, "project.policy_cleared", project.id)

    @router.get("/api/organizations/{organization_id}/policy")
    def org_policy(organization_id: str, request: Request):
        with db.session() as session:
            user = require_user(request, session, settings)
            membership(session, user, organization_id)
            org = session.get(Organization, organization_id)
            assert org is not None
            return {"policy": org.policy, "version": org.policy_version}

    @router.put("/api/organizations/{organization_id}/policy")
    def set_org_policy(organization_id: str, body: PolicyInput, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            org = authorized_org(session, user, organization_id, MANAGERS)
            require_feature(org, "organization_policy")
            org.policy, org.policy_version = body.model_dump(), org.policy_version + 1
            audit(
                session,
                org.id,
                user.id,
                "organization.policy_updated",
                org.id,
                {"version": org.policy_version},
            )
            return {"policy": org.policy, "version": org.policy_version}

    @router.delete("/api/organizations/{organization_id}/policy", status_code=204)
    def clear_org_policy(organization_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings, True)
            org = authorized_org(session, user, organization_id, MANAGERS)
            org.policy, org.policy_version = None, org.policy_version + 1
            audit(session, org.id, user.id, "organization.policy_cleared", org.id)

    @router.get("/api/organizations/{organization_id}/audit")
    def events(
        organization_id: str,
        request: Request,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        with db.session() as session:
            user = require_user(request, session, settings)
            org = authorized_org(session, user, organization_id, MANAGERS)
            require_feature(org, "audit")
            return {
                "events": [
                    {
                        "id": row.id,
                        "actor": row.actor,
                        "action": row.action,
                        "target_id": row.target_id,
                        "details": row.details,
                        "created_at": row.created_at,
                    }
                    for row in session.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.organization_id == org.id)
                        .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
                        .limit(limit)
                        .offset(offset)
                    )
                ]
            }

    @router.get("/api/analyses/{analysis_id}/findings")
    def findings(
        analysis_id: str,
        request: Request,
        severity: str | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        with db.session() as session:
            user = require_user(request, session, settings)
            job, _ = visible_analysis(session, user, analysis_id)
            query = select(Finding).where(Finding.analysis_id == job.id)
            if severity:
                query = query.where(Finding.severity == severity)
            return {
                "normalized_version": job.normalized_version,
                "findings": [
                    {
                        "id": row.id,
                        "type": row.type,
                        "severity": row.severity,
                        "title": row.title,
                        "description": row.description,
                        "evidence": row.evidence,
                    }
                    for row in session.scalars(
                        query.order_by(Finding.id).limit(limit).offset(offset)
                    )
                ],
            }

    @router.get("/api/analyses/{analysis_id}/paths")
    def paths(
        analysis_id: str,
        request: Request,
        phase: Literal["before", "after"] = "after",
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        with db.session() as session:
            user = require_user(request, session, settings)
            job, _ = visible_analysis(session, user, analysis_id)
            rows = session.scalars(
                select(AttackPath)
                .where(AttackPath.analysis_id == job.id, AttackPath.phase == phase)
                .order_by(AttackPath.id)
                .limit(limit)
                .offset(offset)
            )
            return {
                "normalized_version": job.normalized_version,
                "paths": [
                    {
                        "id": row.id,
                        "key": row.path_key,
                        "phase": row.phase,
                        "severity": row.severity,
                        "nodes": row.nodes,
                        "labels": row.labels,
                        "explanation": row.explanation,
                        "reaches_sensitive": row.reaches_sensitive,
                        "hops": [
                            {"position": hop.position, **hop.evidence}
                            for hop in session.scalars(
                                select(AttackPathHop)
                                .where(AttackPathHop.path_id == row.id)
                                .order_by(AttackPathHop.position)
                            )
                        ],
                    }
                    for row in rows
                ],
            }

    @router.get("/api/analyses/{analysis_id}/artifacts")
    def artifacts(analysis_id: str, request: Request):
        with db.session() as session:
            user = require_user(request, session, settings)
            job, org = visible_analysis(session, user, analysis_id)
            return {
                "normalized_version": job.normalized_version,
                "artifacts": [
                    {
                        "id": row.id,
                        "format": row.format,
                        "media_type": row.media_type,
                        "created_at": row.created_at,
                    }
                    for row in session.scalars(
                        select(AnalysisArtifact)
                        .where(AnalysisArtifact.analysis_id == job.id)
                        .order_by(AnalysisArtifact.format)
                    )
                    if row.format != "sarif" or entitlements(org).sarif
                ],
            }

    @router.get("/api/analyses/{analysis_id}/artifacts/{artifact_id}")
    def artifact(analysis_id: str, artifact_id: str, request: Request):
        with db.session(write=True) as session:
            user = require_user(request, session, settings)
            job, org = visible_analysis(session, user, analysis_id)
            org = lock_org(session, org.id)
            job, org = visible_analysis(session, user, analysis_id)
            row = session.get(AnalysisArtifact, artifact_id)
            if row is None or row.analysis_id != job.id:
                raise HTTPException(404, "not_found")
            if row.format == "sarif":
                require_feature(org, "sarif")
            usage_row(session, org).exports += 1
            if row.format == "json":
                return JSONResponse(public_result(json.loads(row.content), entitlements(org).sarif))
            return Response(row.content, media_type=row.media_type)

    return router
