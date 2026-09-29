"""drop_inert_billing_schema

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("billing_events")
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError(
            "Rebuilding organizations requires SQLite foreign keys disabled; "
            "otherwise the table drop cascades into child tables."
        )
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.drop_column("billing_event_created")
        batch_op.drop_column("subscription_status")
        batch_op.drop_column("subscription_id")
        batch_op.drop_column("customer_id")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("customer_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("subscription_id", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "subscription_status", sa.String(length=50), server_default="none", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column("billing_event_created", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.create_unique_constraint("organizations_customer_id_key", ["customer_id"])
        batch_op.create_unique_constraint(
            "organizations_subscription_id_key", ["subscription_id"]
        )
    op.create_table(
        "billing_events",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
