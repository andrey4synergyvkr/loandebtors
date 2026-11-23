"""Создание таблицы попыток отправки.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

SCHEMA = "notification"
TABLE = "message_attempts"
MESSAGES = "messages"
MESSAGE_INDEX = "ix_message_attempts_message"
NUMBER_INDEX = "ux_message_attempts_number"


def upgrade() -> None:
    """Создать таблицу попыток отправки и индексы."""
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(TABLE, schema=SCHEMA):
        return
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("provider_error_code", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('sent', 'transient_failure', 'permanent_failure', 'rate_limited')",
            name="ck_message_attempts_outcome",
        ),
        sa.CheckConstraint("attempt_number >= 1", name="ck_message_attempts_number"),
        sa.ForeignKeyConstraint(
            ["message_id"],
            [f"{SCHEMA}.{MESSAGES}.id"],
            name="fk_message_attempts_message",
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )
    op.create_index(MESSAGE_INDEX, TABLE, ["message_id"], schema=SCHEMA)
    op.create_index(
        NUMBER_INDEX,
        TABLE,
        ["message_id", "attempt_number"],
        unique=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Удалить таблицу попыток отправки."""
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(TABLE, schema=SCHEMA):
        op.drop_table(TABLE, schema=SCHEMA)
