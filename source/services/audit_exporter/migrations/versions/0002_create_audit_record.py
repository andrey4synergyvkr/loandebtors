"""Создание append-only журнала audit.audit_record.

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

SCHEMA = "audit"
TABLE = "audit_record"
APPEND_ONLY_FUNCTION = "reject_audit_record_mutation"
APPEND_ONLY_TRIGGER = "audit_record_append_only"
TRUNCATE_TRIGGER = "audit_record_no_truncate"


def upgrade() -> None:
    """Создать таблицу журнала, индексы и защиту append-only."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        op.create_table(
            TABLE,
            sa.Column("sequence", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
            sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("service", sa.String(length=64), nullable=False),
            sa.Column("actor_type", sa.String(length=32), nullable=False),
            sa.Column("actor_identifier", sa.String(length=255), nullable=True),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("entity_type", sa.String(length=64), nullable=False),
            sa.Column("entity_id", sa.String(length=255), nullable=False),
            sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("channel", sa.String(length=64), nullable=True),
            sa.Column("outcome", sa.String(length=16), nullable=False),
            sa.Column(
                "details",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("correlation_id", sa.String(length=128), nullable=False),
            sa.Column("trace_id", sa.String(length=64), nullable=True),
            sa.Column(
                "ingested_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint("event_id", name="uq_audit_record_event_id"),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_audit_record_occurred_at_sequence",
            TABLE,
            ["occurred_at", "sequence"],
            schema=SCHEMA,
        )
        op.create_index(
            "ix_audit_record_campaign_sequence",
            TABLE,
            ["campaign_id", "sequence"],
            schema=SCHEMA,
        )
        op.create_index(
            "ix_audit_record_channel_sequence",
            TABLE,
            ["channel", "sequence"],
            schema=SCHEMA,
        )
        op.create_index(
            "ix_audit_record_action_sequence",
            TABLE,
            ["action", "sequence"],
            schema=SCHEMA,
        )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.{APPEND_ONLY_FUNCTION}() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '{SCHEMA}.{TABLE} is append-only'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {APPEND_ONLY_TRIGGER} ON {SCHEMA}.{TABLE}")
    op.execute(
        f"""
        CREATE TRIGGER {APPEND_ONLY_TRIGGER}
        BEFORE UPDATE OR DELETE ON {SCHEMA}.{TABLE}
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{APPEND_ONLY_FUNCTION}()
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {TRUNCATE_TRIGGER} ON {SCHEMA}.{TABLE}")
    op.execute(
        f"""
        CREATE TRIGGER {TRUNCATE_TRIGGER}
        BEFORE TRUNCATE ON {SCHEMA}.{TABLE}
        FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.{APPEND_ONLY_FUNCTION}()
        """
    )


def downgrade() -> None:
    """Удалить таблицу журнала и защиту append-only."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE, schema=SCHEMA):
        return
    op.execute(f"DROP TRIGGER IF EXISTS {APPEND_ONLY_TRIGGER} ON {SCHEMA}.{TABLE}")
    op.execute(f"DROP TRIGGER IF EXISTS {TRUNCATE_TRIGGER} ON {SCHEMA}.{TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{APPEND_ONLY_FUNCTION}()")
    op.drop_table(TABLE, schema=SCHEMA)
