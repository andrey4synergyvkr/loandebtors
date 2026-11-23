"""SQLAlchemy-модели инфраструктуры Scheduler."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

OUTBOX_TABLE: str = "outbox"
CAMPAIGN_SCHEDULE_TABLE: str = "campaign_schedule"
CANCELLED_CAMPAIGN_TABLE: str = "cancelled_campaign"
SCHEDULER_SCHEMA: str = "scheduler"


class Base(DeclarativeBase):
    """Базовый класс декларативных моделей."""


class OutboxRow(Base):
    """Запись транзакционного outbox.

    Одна таблица используется для всех событий планировщика: command
    campaign.start и событий audit. Тип события задается полем event_type.

    Attributes:
        id: Идентификатор записи.
        event_type: Тип события.
        exchange: Имя exchange RabbitMQ.
        routing_key: Routing key публикации.
        payload: JSON-тело сообщения.
        headers: JSON-заголовки сообщения.
        occurred_at: Время события в UTC.
        available_at: Время готовности к публикации.
        published_at: Время успешной публикации.
        attempts: Число выполненных попыток.
        last_error: Описание последней ошибки.
        created_at: Время создания записи.
    """

    __tablename__ = OUTBOX_TABLE
    __table_args__ = (
        Index(
            "ix_outbox_ready",
            "available_at",
            postgresql_where=text("published_at IS NULL"),
        ),
        {"schema": SCHEDULER_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    exchange: Mapped[str] = mapped_column(String(255), nullable=False)
    routing_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    headers: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class CampaignScheduleRow(Base):
    """Расписание запуска кампании.

    Attributes:
        campaign_id: Идентификатор кампании и первичный ключ.
        schedule_kind: Вид расписания.
        timezone: Часовой пояс IANA.
        run_at: Время разового запуска.
        cron: Выражение cron для повторяющегося запуска.
        status: Состояние задания.
        next_run_at: Ближайший плановый запуск.
        last_triggered_at: Время последнего срабатывания.
        correlation_id: Корреляция исходной команды.
        created_at: Время создания записи.
        updated_at: Время последнего изменения.
    """

    __tablename__ = CAMPAIGN_SCHEDULE_TABLE
    __table_args__ = (
        CheckConstraint(
            "schedule_kind IN ('one_off', 'cron')",
            name="ck_campaign_schedule_kind",
        ),
        CheckConstraint(
            "(schedule_kind = 'one_off' AND run_at IS NOT NULL AND cron IS NULL) "
            "OR (schedule_kind = 'cron' AND cron IS NOT NULL AND run_at IS NULL)",
            name="ck_campaign_schedule_spec",
        ),
        Index("ix_campaign_schedule_active", "status", "next_run_at"),
        {"schema": SCHEDULER_SCHEMA},
    )

    campaign_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    schedule_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cron: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class CancelledCampaignRow(Base):
    """Отметка об отмене кампании.

    Отметка позволяет обрабатывать команды campaign.scheduled и
    campaign.cancelled в любом порядке. Если отмена пришла раньше, регистрация
    расписания увидит отметку и не создаст задание.

    Attributes:
        campaign_id: Идентификатор отмененной кампании.
        occurred_at: Время отмены из команды campaign.cancelled.
        created_at: Время создания отметки.
    """

    __tablename__ = CANCELLED_CAMPAIGN_TABLE
    __table_args__ = (
        Index("ix_cancelled_campaign_occurred_at", "occurred_at"),
        {"schema": SCHEDULER_SCHEMA},
    )

    campaign_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
