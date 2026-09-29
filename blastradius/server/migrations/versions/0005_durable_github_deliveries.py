"""durable_github_deliveries

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29 08:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("github_deliveries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("payload", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("next_attempt_at", sa.Float(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_github_deliveries_status"), ["status"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("github_deliveries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_github_deliveries_status"))
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("payload")
