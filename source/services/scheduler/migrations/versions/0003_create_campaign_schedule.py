"""Создание таблицы расписаний кампаний.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SCHEMA = "scheduler"
TABLE = "campaign_schedule"
ACTIVE_INDEX = "ix_campaign_schedule_active"


def upgrade() -> None:
    """Создать таблицу campaign_schedule и индекс активных расписаний."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        op.create_table(
            TABLE,
            sa.Column("campaign_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("schedule_kind", sa.String(length=20), nullable=False),
            sa.Column("timezone", sa.String(length=64), nullable=False),
            sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cron", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("correlation_id", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint(
                "schedule_kind IN ('one_off', 'cron')",
                name="ck_campaign_schedule_kind",
            ),
            sa.CheckConstraint(
                "(schedule_kind = 'one_off' AND run_at IS NOT NULL AND cron IS NULL) "
                "OR (schedule_kind = 'cron' AND cron IS NOT NULL AND run_at IS NULL)",
                name="ck_campaign_schedule_spec",
            ),
            schema=SCHEMA,
        )
        op.create_index(
            ACTIVE_INDEX,
            TABLE,
            ["status", "next_run_at"],
            schema=SCHEMA,
        )
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE, schema=SCHEMA)}
    if ACTIVE_INDEX not in existing_indexes:
        op.create_index(
            ACTIVE_INDEX,
            TABLE,
            ["status", "next_run_at"],
            schema=SCHEMA,
        )


def downgrade() -> None:
    """Удалить таблицу campaign_schedule и индекс."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        return
    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE, schema=SCHEMA)}
    if ACTIVE_INDEX in existing_indexes:
        op.drop_index(ACTIVE_INDEX, table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
