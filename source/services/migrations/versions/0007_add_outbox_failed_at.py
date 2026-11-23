"""Добавление признака окончательного отказа публикации outbox.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

SCHEMA = "notification"
TABLE = "outbox"
COLUMN = "failed_at"
READY_INDEX = "ix_outbox_ready"


def upgrade() -> None:
    """Добавить failed_at и обновить частичный индекс готовности."""
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(TABLE, schema=SCHEMA)}
    if COLUMN not in columns:
        op.add_column(
            TABLE,
            sa.Column(COLUMN, sa.DateTime(timezone=True), nullable=True),
            schema=SCHEMA,
        )
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.{READY_INDEX}")
    op.create_index(
        READY_INDEX,
        TABLE,
        ["available_at"],
        schema=SCHEMA,
        postgresql_where=sa.text("published_at IS NULL AND failed_at IS NULL"),
    )


def downgrade() -> None:
    """Удалить failed_at и вернуть прежний индекс."""
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.{READY_INDEX}")
    op.create_index(
        READY_INDEX,
        TABLE,
        ["available_at"],
        schema=SCHEMA,
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.drop_column(TABLE, COLUMN, schema=SCHEMA)
