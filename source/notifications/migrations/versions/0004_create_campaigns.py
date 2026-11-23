"""Создание таблицы кампаний.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

SCHEMA = "notification"
TABLE = "campaigns"
STATUS_INDEX = "ix_campaigns_status"
CREATED_INDEX = "ix_campaigns_created_at"
TEMPLATE_FK = "fk_campaigns_template"


def upgrade() -> None:
    """Создать таблицу кампаний и индексы."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        op.create_table(
            TABLE,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("template_key", sa.String(length=100), nullable=False),
            sa.Column("template_version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column(
                "selection",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column(
                "schedule",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
            sa.Column(
                "selected_debtors",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("selection_expected", sa.Integer(), nullable=True),
            sa.Column("selection_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "status IN ('draft', 'scheduled', 'running', 'completed', 'cancelled', 'failed')",
                name="ck_campaigns_status",
            ),
            sa.CheckConstraint(
                "template_version >= 1",
                name="ck_campaigns_template_version",
            ),
            sa.CheckConstraint(
                "selected_debtors >= 0",
                name="ck_campaigns_selected_debtors",
            ),
            sa.CheckConstraint(
                "selection_expected IS NULL OR selection_expected >= 0",
                name="ck_campaigns_selection_expected",
            ),
            sa.ForeignKeyConstraint(
                ["template_key", "template_version"],
                [f"{SCHEMA}.templates.key", f"{SCHEMA}.templates.version"],
                name=TEMPLATE_FK,
                ondelete="RESTRICT",
            ),
            schema=SCHEMA,
        )
        _create_indexes()
        return

    _create_indexes()


def _create_indexes() -> None:
    """Создать недостающие индексы таблицы кампаний."""
    inspector = sa.inspect(op.get_bind())
    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE, schema=SCHEMA)}
    if STATUS_INDEX not in existing_indexes:
        op.create_index(STATUS_INDEX, TABLE, ["status"], schema=SCHEMA)
    if CREATED_INDEX not in existing_indexes:
        op.create_index(CREATED_INDEX, TABLE, ["created_at"], schema=SCHEMA)


def downgrade() -> None:
    """Удалить таблицу кампаний и индексы."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        return
    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE, schema=SCHEMA)}
    if CREATED_INDEX in existing_indexes:
        op.drop_index(CREATED_INDEX, table_name=TABLE, schema=SCHEMA)
    if STATUS_INDEX in existing_indexes:
        op.drop_index(STATUS_INDEX, table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
