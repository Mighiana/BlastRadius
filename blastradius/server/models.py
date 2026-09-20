from __future__ import annotations

import time
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def identifier() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    issuer: Mapped[str] = mapped_column(String(512))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320), default="")
    email_verified: Mapped[bool] = mapped_column(default=False, server_default=false())
    name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[float] = mapped_column(default=time.time)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(100))
    plan: Mapped[str] = mapped_column(String(20), default="free")
    plan_limits: Mapped[dict[str, int] | None] = mapped_column(JSON)
    policy: Mapped[dict | None] = mapped_column(JSON)
    policy_version: Mapped[int] = mapped_column(default=0, server_default="0")
    updated_at: Mapped[float | None]
    customer_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    subscription_status: Mapped[str] = mapped_column(String(50), default="none")
    billing_event_created: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[float] = mapped_column(default=time.time)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'developer', 'viewer')", name="membership_role"
        ),
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20))


class LoginSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str | None] = mapped_column(String(36), default=identifier, unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    csrf_token: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[float] = mapped_column(index=True)
    created_at: Mapped[float | None] = mapped_column(default=time.time)
    oidc_authenticated: Mapped[bool] = mapped_column(default=False, server_default=false())


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    repository: Mapped[str] = mapped_column(String(255), default="", server_default="")
    repository_provider: Mapped[str] = mapped_column(
        String(20), default="manual", server_default="manual"
    )
    default_branch: Mapped[str] = mapped_column(String(120), default="main", server_default="main")
    environment: Mapped[str] = mapped_column(String(100), default="", server_default="")
    terraform_root: Mapped[str] = mapped_column(String(255), default=".", server_default=".")
    archived_at: Mapped[float | None]
    updated_at: Mapped[float | None]
    policy: Mapped[dict | None] = mapped_column(JSON)
    policy_version: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[float] = mapped_column(default=time.time)


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        Index("ix_analyses_org_created", "organization_id", "created_at"),
        Index("ix_analyses_project_created", "project_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    base_label: Mapped[str] = mapped_column(String(120))
    candidate_label: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[float] = mapped_column(default=time.time)
    started_at: Mapped[float | None]
    completed_at: Mapped[float | None]
    result: Mapped[dict | None] = mapped_column(JSON)
    input_type: Mapped[str | None] = mapped_column(String(20))
    base_ref: Mapped[str | None] = mapped_column(String(120))
    candidate_ref: Mapped[str | None] = mapped_column(String(120), index=True)
    base_sha: Mapped[str | None] = mapped_column(String(64))
    candidate_sha: Mapped[str | None] = mapped_column(String(64))
    decision: Mapped[str | None] = mapped_column(String(40), index=True)
    score_before: Mapped[int | None]
    score_after: Mapped[int | None]
    risk_before: Mapped[str | None] = mapped_column(String(20))
    risk_after: Mapped[str | None] = mapped_column(String(20))
    critical_paths_added: Mapped[int | None]
    critical_paths_removed: Mapped[int | None]
    normalized_version: Mapped[int | None]
    policy_snapshot: Mapped[dict | None] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(36))


class Usage(Base):
    __tablename__ = "usage"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    period: Mapped[str] = mapped_column(String(7), primary_key=True)
    analyses: Mapped[int] = mapped_column(default=0)
    exports: Mapped[int] = mapped_column(default=0, server_default="0")


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'developer', 'viewer')", name="invitation_role"),
        Index("ix_invitations_org_expiry", "organization_id", "expires_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[float] = mapped_column(default=time.time)
    expires_at: Mapped[float]
    revoked_at: Mapped[float | None]
    accepted_at: Mapped[float | None]


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_org_created", "organization_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(default=time.time)


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(default=time.time)


class AttackPath(Base):
    __tablename__ = "attack_paths"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    phase: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(20))
    path_key: Mapped[str] = mapped_column(Text)
    nodes: Mapped[list[str]] = mapped_column(JSON)
    labels: Mapped[list[str]] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text)
    reaches_sensitive: Mapped[bool]


class AttackPathHop(Base):
    __tablename__ = "attack_path_hops"
    path_id: Mapped[str] = mapped_column(
        ForeignKey("attack_paths.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    source_node: Mapped[str] = mapped_column(Text)
    target_node: Mapped[str] = mapped_column(Text)
    relationship: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON)


class AnalysisArtifact(Base):
    __tablename__ = "analysis_artifacts"
    __table_args__ = (UniqueConstraint("analysis_id", "format"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[str] = mapped_column(String(20))
    media_type: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(default=time.time)


class BillingEvent(Base):
    __tablename__ = "billing_events"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[float] = mapped_column(default=time.time)


class GitHubInstallation(Base):
    __tablename__ = "github_installations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int] = mapped_column(BigInteger)
    account_login: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="active")
    verified_at: Mapped[float] = mapped_column(default=time.time)


class RepositoryConnection(Base):
    __tablename__ = "repository_connections"
    __table_args__ = (UniqueConstraint("installation_id", "repository_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    installation_id: Mapped[int] = mapped_column(
        ForeignKey("github_installations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True
    )
    repository_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    full_name: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[float] = mapped_column(default=time.time)


class GitHubDelivery(Base):
    __tablename__ = "github_deliveries"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    body_hash: Mapped[str] = mapped_column(String(64), unique=True)
    event: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    attempts: Mapped[int] = mapped_column(default=1)
    error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[float] = mapped_column(default=time.time)


class GitHubRun(Base):
    __tablename__ = "github_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("repository_connections.id", ondelete="CASCADE"), index=True
    )
    analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="SET NULL"), unique=True
    )
    pull_number: Mapped[int]
    base_sha: Mapped[str] = mapped_column(String(40))
    head_sha: Mapped[str] = mapped_column(String(40))
    head_repository_id: Mapped[int] = mapped_column(BigInteger)
    base_ref: Mapped[str] = mapped_column(String(120))
    head_ref: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    error: Mapped[str | None] = mapped_column(String(100))
    check_id: Mapped[int | None] = mapped_column(BigInteger)
    check_uncertain: Mapped[bool] = mapped_column(default=False)
    comment_uncertain: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[float] = mapped_column(default=time.time)


class CommercialLock(Base):
    __tablename__ = "commercial_lock"
    id: Mapped[int] = mapped_column(primary_key=True)


class BetaInterest(Base):
    __tablename__ = "beta_interest"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(320))
    company: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(80))
    team_size: Mapped[int | None]
    repository_count: Mapped[int | None]
    primary_cloud: Mapped[str | None] = mapped_column(String(20))
    source_control: Mapped[str | None] = mapped_column(String(20))
    problem: Mapped[str] = mapped_column(String(1000))
    privacy_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[float] = mapped_column(default=time.time, index=True)


class AnalysisFeedback(Base):
    __tablename__ = "analysis_feedback"
    __table_args__ = (UniqueConstraint("analysis_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    useful: Mapped[bool]
    message: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[float] = mapped_column(default=time.time, index=True)
    updated_at: Mapped[float] = mapped_column(default=time.time)


class ProductEvent(Base):
    __tablename__ = "product_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    analysis_id: Mapped[str | None] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"))
    created_at: Mapped[float] = mapped_column(default=time.time, index=True)
