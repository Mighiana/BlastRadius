from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("issuer", "subject"),
    )
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("plan", sa.String(20), nullable=False),
        sa.Column("customer_id", sa.String(255), unique=True),
        sa.Column("subscription_id", sa.String(255), unique=True),
        sa.Column("subscription_status", sa.String(50), nullable=False),
        sa.Column("billing_event_created", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_table(
        "memberships",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(20), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("csrf_token", sa.String(100), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])
    op.create_table(
        "analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("base_label", sa.String(120), nullable=False),
        sa.Column("candidate_label", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String(100)),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float()),
        sa.Column("completed_at", sa.Float()),
        sa.Column("result", sa.JSON()),
    )
    for name in ("project_id", "organization_id", "status"):
        op.create_index(f"ix_analyses_{name}", "analyses", [name])
    op.create_table(
        "usage",
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("period", sa.String(7), primary_key=True),
        sa.Column("analyses", sa.Integer(), nullable=False),
    )
    op.create_table(
        "billing_events",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("created_at", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "billing_events",
        "usage",
        "analyses",
        "projects",
        "sessions",
        "memberships",
        "organizations",
        "users",
    ):
        op.drop_table(table)
