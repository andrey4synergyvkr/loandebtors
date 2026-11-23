"""Создание таблиц email-шаблонов, попыток и идемпотентности.

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

SCHEMA = "email_channel"
TEMPLATES_TABLE = "email_templates"
ATTEMPTS_TABLE = "send_attempts"
PROCESSED_TABLE = "processed_messages"


def upgrade() -> None:
    """Создать таблицы email-шаблонов, попыток и обработанных сообщений."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TEMPLATES_TABLE, schema=SCHEMA):
        op.create_table(
            TEMPLATES_TABLE,
            sa.Column("key", sa.String(length=100), primary_key=True),
            sa.Column("version", sa.Integer(), primary_key=True),
            sa.Column("locale", sa.String(length=10), primary_key=True),
            sa.Column("subject_template", sa.Text(), nullable=False),
            sa.Column("html_template", sa.Text(), nullable=False),
            sa.Column("plain_text_template", sa.Text(), nullable=False),
            sa.Column(
                "required_variables",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            schema=SCHEMA,
        )

    if not inspector.has_table(ATTEMPTS_TABLE, schema=SCHEMA):
        op.create_table(
            ATTEMPTS_TABLE,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("attempt_number", sa.Integer(), nullable=False),
            sa.Column("recipient", sa.String(length=320), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("outcome", sa.String(length=32), nullable=True),
            sa.Column("provider_message_id", sa.String(length=255), nullable=True),
            sa.Column("provider_error_code", sa.String(length=100), nullable=True),
            sa.Column("provider_error_message", sa.Text(), nullable=True),
            sa.UniqueConstraint(
                "message_id",
                "attempt_number",
                name="uq_send_attempt_message",
            ),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_send_attempt_message",
            ATTEMPTS_TABLE,
            ["message_id"],
            schema=SCHEMA,
        )

    if not inspector.has_table(PROCESSED_TABLE, schema=SCHEMA):
        op.create_table(
            PROCESSED_TABLE,
            sa.Column("message_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
            schema=SCHEMA,
        )


def downgrade() -> None:
    """Удалить таблицы email-шаблонов, попыток и обработанных сообщений."""
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(PROCESSED_TABLE, schema=SCHEMA):
        op.drop_table(PROCESSED_TABLE, schema=SCHEMA)
    if inspector.has_table(ATTEMPTS_TABLE, schema=SCHEMA):
        op.drop_table(ATTEMPTS_TABLE, schema=SCHEMA)
    if inspector.has_table(TEMPLATES_TABLE, schema=SCHEMA):
        op.drop_table(TEMPLATES_TABLE, schema=SCHEMA)
