"""product_event_counter

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

# Row triggers keep commercial_lock.event_count exact for every insert and delete,
# including trims, retention cleanup and ON DELETE CASCADE from parent rows.
SQLITE_TRIGGERS = (
    "CREATE TRIGGER product_events_count_insert AFTER INSERT ON product_events"
    " BEGIN UPDATE commercial_lock SET event_count = event_count + 1 WHERE id = 1; END",
    "CREATE TRIGGER product_events_count_delete AFTER DELETE ON product_events"
    " BEGIN UPDATE commercial_lock SET event_count = event_count - 1 WHERE id = 1; END",
)
POSTGRESQL_TRIGGERS = (
    """
    CREATE FUNCTION product_events_count() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            UPDATE commercial_lock SET event_count = event_count + 1 WHERE id = 1;
        ELSE
            UPDATE commercial_lock SET event_count = event_count - 1 WHERE id = 1;
        END IF;
        RETURN NULL;
    END
    $$
    """,
    "CREATE TRIGGER product_events_count AFTER INSERT OR DELETE ON product_events"
    " FOR EACH ROW EXECUTE FUNCTION product_events_count()",
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("commercial_lock", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("event_count", sa.Integer(), server_default="0", nullable=False)
        )
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("LOCK TABLE commercial_lock, product_events IN EXCLUSIVE MODE")
    op.execute(
        "UPDATE commercial_lock SET event_count = (SELECT count(*) FROM product_events)"
    )
    if dialect == "sqlite":
        statements = SQLITE_TRIGGERS
    elif dialect == "postgresql":
        statements = POSTGRESQL_TRIGGERS
    else:
        raise RuntimeError(f"unsupported database dialect: {dialect}")
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS product_events_count ON product_events")
        op.execute("DROP FUNCTION IF EXISTS product_events_count()")
    else:
        op.execute("DROP TRIGGER IF EXISTS product_events_count_insert")
        op.execute("DROP TRIGGER IF EXISTS product_events_count_delete")
    with op.batch_alter_table("commercial_lock", schema=None) as batch_op:
        batch_op.drop_column("event_count")
