"""Создание таблицы отметок об отмене кампаний.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

SCHEMA = "scheduler"
TABLE = "cancelled_campaign"
OCCURRED_INDEX = "ix_cancelled_campaign_occurred_at"


def upgrade() -> None:
    """Создать таблицу отметок об отмене и индекс по времени."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        op.create_table(
            TABLE,
            sa.Column("campaign_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            schema=SCHEMA,
        )
        op.create_index(
            OCCURRED_INDEX,
            TABLE,
            ["occurred_at"],
            schema=SCHEMA,
        )
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE, schema=SCHEMA)}
    if OCCURRED_INDEX not in existing_indexes:
        op.create_index(
            OCCURRED_INDEX,
            TABLE,
            ["occurred_at"],
            schema=SCHEMA,
        )


def downgrade() -> None:
    """Удалить таблицу отметок об отмене и индекс."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        return
    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE, schema=SCHEMA)}
    if OCCURRED_INDEX in existing_indexes:
        op.drop_index(OCCURRED_INDEX, table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
