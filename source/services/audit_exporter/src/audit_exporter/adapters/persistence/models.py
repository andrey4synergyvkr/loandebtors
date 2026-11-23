"""SQLAlchemy-модели инфраструктуры Audit Exporter."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

AUDIT_SCHEMA: str = "audit"
AUDIT_RECORD_TABLE: str = "audit_record"


class Base(DeclarativeBase):
    """Базовый класс декларативных моделей."""


class AuditRecordRow(Base):
    """Запись append-only журнала аудита.

    Attributes:
        sequence: Порядковый номер записи.
        event_id: Идентификатор события, ключ идемпотентности.
        occurred_at: Время действия в сервисе-источнике.
        service: Источник события.
        actor_type: Тип инициатора.
        actor_identifier: Логин сотрудника или имя сервиса.
        action: Выполненное действие.
        entity_type: Тип сущности.
        entity_id: Идентификатор сущности.
        campaign_id: Идентификатор кампании.
        message_id: Идентификатор сообщения.
        channel: Код канала.
        outcome: Результат действия.
        details: Дополнительные поля без персональных данных.
        correlation_id: Идентификатор сценария.
        trace_id: Идентификатор трейса.
        ingested_at: Время записи в журнал.
    """

    __tablename__ = AUDIT_RECORD_TABLE
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_audit_record_event_id"),
        Index("ix_audit_record_occurred_at_sequence", "occurred_at", "sequence"),
        Index("ix_audit_record_campaign_sequence", "campaign_id", "sequence"),
        Index("ix_audit_record_channel_sequence", "channel", "sequence"),
        Index("ix_audit_record_action_sequence", "action", "sequence"),
        {"schema": AUDIT_SCHEMA},
    )

    sequence: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    service: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    campaign_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    message_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
