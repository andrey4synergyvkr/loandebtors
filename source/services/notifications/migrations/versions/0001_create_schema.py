"""Создание схемы notification.

Revision ID: 0001
Revises:
Create Date: 2026-11-21
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS notification")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS notification CASCADE")
