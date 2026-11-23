"""Создание таблицы логических шаблонов.

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

SCHEMA = "notification"
TABLE = "templates"
STATUS_INDEX = "ix_templates_status"
ACTIVE_INDEX = "ux_templates_active_key"


def upgrade() -> None:
    """Создать таблицу версий шаблонов и индексы."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        op.create_table(
            TABLE,
            sa.Column("key", sa.String(length=100), primary_key=True),
            sa.Column("version", sa.Integer(), primary_key=True),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column(
                "required_variables",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("version >= 1", name="ck_templates_version_positive"),
            sa.CheckConstraint(
                "status IN ('draft', 'active', 'archived')",
                name="ck_templates_status",
            ),
            sa.CheckConstraint("length(description) > 0", name="ck_templates_description"),
            sa.CheckConstraint(
                "jsonb_typeof(required_variables) = 'array'",
                name="ck_templates_variables_array",
            ),
            schema=SCHEMA,
        )
        _create_indexes()
        return

    _create_indexes()


def _create_indexes() -> None:
    """Создать недостающие индексы таблицы шаблонов."""
    inspector = sa.inspect(op.get_bind())
    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE, schema=SCHEMA)}
    if STATUS_INDEX not in existing_indexes:
        op.create_index(STATUS_INDEX, TABLE, ["status"], schema=SCHEMA)
    if ACTIVE_INDEX not in existing_indexes:
        op.create_index(
            ACTIVE_INDEX,
            TABLE,
            ["key"],
            unique=True,
            schema=SCHEMA,
            postgresql_where=sa.text("status = 'active'"),
        )


def downgrade() -> None:
    """Удалить таблицу версий шаблонов и индексы."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        return
    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE, schema=SCHEMA)}
    if ACTIVE_INDEX in existing_indexes:
        op.drop_index(ACTIVE_INDEX, table_name=TABLE, schema=SCHEMA)
    if STATUS_INDEX in existing_indexes:
        op.drop_index(STATUS_INDEX, table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
