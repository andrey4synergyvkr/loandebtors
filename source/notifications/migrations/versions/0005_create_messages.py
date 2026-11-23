"""Снимки должников, сообщения и отметка создания сообщений.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

SCHEMA = "notification"
CAMPAIGNS = "campaigns"
SNAPSHOTS = "debtor_snapshots"
MESSAGES = "messages"
SNAPSHOT_INDEX = "ix_debtor_snapshots_campaign"
MESSAGE_CAMPAIGN_INDEX = "ix_messages_campaign"
MESSAGE_STATUS_INDEX = "ix_messages_status"
MESSAGE_NEXT_INDEX = "ix_messages_next_attempt"
MESSAGE_IDEMPOTENCY_INDEX = "ux_messages_idempotency"


def upgrade() -> None:
    """Добавить отметку сообщений и создать таблицы выборки и сообщений."""
    inspector = sa.inspect(op.get_bind())
    campaign_columns = {
        column["name"] for column in inspector.get_columns(CAMPAIGNS, schema=SCHEMA)
    }
    if "messages_created_at" not in campaign_columns:
        op.add_column(
            CAMPAIGNS,
            sa.Column("messages_created_at", sa.DateTime(timezone=True), nullable=True),
            schema=SCHEMA,
        )

    if not inspector.has_table(SNAPSHOTS, schema=SCHEMA):
        op.create_table(
            SNAPSHOTS,
            sa.Column("campaign_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("debtor_id", sa.String(length=100), primary_key=True),
            sa.Column("full_name", sa.Text(), nullable=False),
            sa.Column(
                "contacts",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column(
                "debts",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["campaign_id"],
                [f"{SCHEMA}.{CAMPAIGNS}.id"],
                name="fk_debtor_snapshots_campaign",
                ondelete="CASCADE",
            ),
            schema=SCHEMA,
        )
        op.create_index(SNAPSHOT_INDEX, SNAPSHOTS, ["campaign_id"], schema=SCHEMA)

    if not inspector.has_table(MESSAGES, schema=SCHEMA):
        op.create_table(
            MESSAGES,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("debtor_id", sa.String(length=100), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("template_key", sa.String(length=100), nullable=False),
            sa.Column("template_version", sa.Integer(), nullable=False),
            sa.Column(
                "variables",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column(
                "recipient",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column("idempotency_key", sa.String(length=300), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column(
                "attempt_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_code", sa.String(length=100), nullable=True),
            sa.Column("last_error_message", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "status IN ('pending', 'queued', 'sent', 'failed', 'cancelled')",
                name="ck_messages_status",
            ),
            sa.CheckConstraint("template_version >= 1", name="ck_messages_template_version"),
            sa.CheckConstraint("attempt_count >= 0", name="ck_messages_attempt_count"),
            sa.CheckConstraint("max_attempts >= 1", name="ck_messages_max_attempts"),
            sa.ForeignKeyConstraint(
                ["campaign_id"],
                [f"{SCHEMA}.{CAMPAIGNS}.id"],
                name="fk_messages_campaign",
                ondelete="CASCADE",
            ),
            schema=SCHEMA,
        )
        op.create_index(MESSAGE_CAMPAIGN_INDEX, MESSAGES, ["campaign_id"], schema=SCHEMA)
        op.create_index(MESSAGE_STATUS_INDEX, MESSAGES, ["status"], schema=SCHEMA)
        op.create_index(
            MESSAGE_NEXT_INDEX,
            MESSAGES,
            ["next_attempt_at"],
            schema=SCHEMA,
        )
        op.create_index(
            MESSAGE_IDEMPOTENCY_INDEX,
            MESSAGES,
            ["idempotency_key"],
            unique=True,
            schema=SCHEMA,
        )


def downgrade() -> None:
    """Удалить таблицы сообщений и снимков и отметку создания сообщений."""
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(MESSAGES, schema=SCHEMA):
        op.drop_table(MESSAGES, schema=SCHEMA)
    if inspector.has_table(SNAPSHOTS, schema=SCHEMA):
        op.drop_table(SNAPSHOTS, schema=SCHEMA)
    campaign_columns = {
        column["name"] for column in inspector.get_columns(CAMPAIGNS, schema=SCHEMA)
    }
    if "messages_created_at" in campaign_columns:
        op.drop_column(CAMPAIGNS, "messages_created_at", schema=SCHEMA)
