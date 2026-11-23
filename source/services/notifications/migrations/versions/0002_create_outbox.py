"""Создание таблицы outbox.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SCHEMA = "notification"
TABLE = "outbox"
READY_INDEX = "ix_outbox_ready"


def upgrade() -> None:
    """Создать таблицу outbox и индекс готовых записей."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        op.create_table(
            TABLE,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("event_type", sa.String(length=100), nullable=False),
            sa.Column("exchange", sa.String(length=255), nullable=False),
            sa.Column("routing_key", sa.String(length=255), nullable=False),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column(
                "headers",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            schema=SCHEMA,
        )
        op.create_index(
            READY_INDEX,
            TABLE,
            ["available_at"],
            schema=SCHEMA,
            postgresql_where=sa.text("published_at IS NULL"),
        )
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE, schema=SCHEMA)}
    if READY_INDEX not in existing_indexes:
        op.create_index(
            READY_INDEX,
            TABLE,
            ["available_at"],
            schema=SCHEMA,
            postgresql_where=sa.text("published_at IS NULL"),
        )


def downgrade() -> None:
    """Удалить таблицу outbox и индекс."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        return
    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE, schema=SCHEMA)}
    if READY_INDEX in existing_indexes:
        op.drop_index(READY_INDEX, table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
