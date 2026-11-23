"""Создание таблицы настроек SMTP-адаптера.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SCHEMA = "email_channel"
TABLE = "smtp_config"


def upgrade() -> None:
    """Создать таблицу smtp_config с единственной строкой настроек."""
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(TABLE, schema=SCHEMA):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("password_ref", sa.String(length=255), nullable=False),
        sa.Column("from_address", sa.String(length=320), nullable=False),
        sa.Column("from_name", sa.String(length=200), nullable=False),
        sa.Column("use_starttls", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("rate_limit_per_second", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Удалить таблицу настроек."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        return
    op.drop_table(TABLE, schema=SCHEMA)
