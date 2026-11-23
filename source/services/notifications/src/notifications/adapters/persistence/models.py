"""SQLAlchemy-модели инфраструктуры Notifications."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
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
TEMPLATES_TABLE: str = "templates"
CAMPAIGNS_TABLE: str = "campaigns"
DEBTOR_SNAPSHOTS_TABLE: str = "debtor_snapshots"
MESSAGES_TABLE: str = "messages"
MESSAGE_ATTEMPTS_TABLE: str = "message_attempts"
NOTIFICATION_SCHEMA: str = "notification"


class Base(DeclarativeBase):
    """Базовый класс декларативных моделей."""


class OutboxRow(Base):
    """Запись транзакционного outbox.

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
        failed_at: Время окончательного отказа публикации.
        attempts: Число выполненных попыток.
        last_error: Описание последней ошибки.
        created_at: Время создания записи.
    """

    __tablename__ = OUTBOX_TABLE
    __table_args__ = (
        Index(
            "ix_outbox_ready",
            "available_at",
            postgresql_where=text("published_at IS NULL AND failed_at IS NULL"),
        ),
        {"schema": NOTIFICATION_SCHEMA},
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
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class TemplateRow(Base):
    """Версия логического шаблона уведомления.

    Attributes:
        key: Логический ключ шаблона.
        version: Версия шаблона, уникальна в пределах ключа.
        description: Назначение шаблона для оператора.
        required_variables: Переменные, обязательные для рендеринга.
        status: Статус версии.
        created_at: Время создания версии.
        updated_at: Время последнего изменения.
    """

    __tablename__ = TEMPLATES_TABLE
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_templates_version_positive"),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_templates_status",
        ),
        CheckConstraint("length(description) > 0", name="ck_templates_description"),
        CheckConstraint(
            "jsonb_typeof(required_variables) = 'array'",
            name="ck_templates_variables_array",
        ),
        Index("ix_templates_status", "status"),
        Index(
            "ux_templates_active_key",
            "key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        {"schema": NOTIFICATION_SCHEMA},
    )

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_variables: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CampaignRow(Base):
    """Кампания рассылки.

    Attributes:
        id: Идентификатор кампании.
        name: Человекочитаемое имя для оператора.
        channel: Канал рассылки.
        template_key: Логический ключ шаблона.
        template_version: Зафиксированная версия шаблона.
        status: Состояние жизненного цикла.
        selection: Параметры выборки из АБС.
        schedule: Правило запуска или None.
        selected_debtors: Сколько должников выгружено.
        selection_expected: Ожидаемое число должников.
        selection_completed_at: Время полной выгрузки.
        messages_created_at: Время создания сообщений после выгрузки.
        created_at: Время создания.
        updated_at: Время последнего изменения.
        scheduled_at: Время постановки в расписание.
        started_at: Время старта.
        finished_at: Время завершения.
        cancelled_at: Время отмены.
        failure_reason: Причина статуса failed.
    """

    __tablename__ = CAMPAIGNS_TABLE
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'scheduled', 'running', 'completed', 'cancelled', 'failed')",
            name="ck_campaigns_status",
        ),
        CheckConstraint("template_version >= 1", name="ck_campaigns_template_version"),
        CheckConstraint("selected_debtors >= 0", name="ck_campaigns_selected_debtors"),
        CheckConstraint(
            "selection_expected IS NULL OR selection_expected >= 0",
            name="ck_campaigns_selection_expected",
        ),
        ForeignKeyConstraint(
            ["template_key", "template_version"],
            [
                f"{NOTIFICATION_SCHEMA}.{TEMPLATES_TABLE}.key",
                f"{NOTIFICATION_SCHEMA}.{TEMPLATES_TABLE}.version",
            ],
            name="fk_campaigns_template",
        ),
        Index("ix_campaigns_status", "status"),
        Index("ix_campaigns_created_at", "created_at"),
        {"schema": NOTIFICATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    selection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schedule: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    selected_debtors: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    selection_expected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selection_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    messages_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class DebtorSnapshotRow(Base):
    """Снимок должника, сохраненный для кампании.

    Attributes:
        campaign_id: Кампания-владелец снимка.
        debtor_id: Идентификатор должника в АБС.
        full_name: Имя для персонализации.
        contacts: Контакты должника в JSONB.
        debts: Задолженности должника в JSONB.
        fetched_at: Время получения данных из АБС.
    """

    __tablename__ = DEBTOR_SNAPSHOTS_TABLE
    __table_args__ = (
        ForeignKeyConstraint(
            ["campaign_id"],
            [f"{NOTIFICATION_SCHEMA}.{CAMPAIGNS_TABLE}.id"],
            name="fk_debtor_snapshots_campaign",
            ondelete="CASCADE",
        ),
        Index("ix_debtor_snapshots_campaign", "campaign_id"),
        {"schema": NOTIFICATION_SCHEMA},
    )

    campaign_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    debtor_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    contacts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    debts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageRow(Base):
    """Сообщение кампании.

    Attributes:
        id: Идентификатор сообщения.
        campaign_id: Кампания-владелец.
        debtor_id: Должник-получатель.
        channel: Канал доставки.
        template_key: Логический шаблон.
        template_version: Версия шаблона.
        variables: Переменные рендеринга.
        recipient: Получатель в формате канала.
        idempotency_key: Ключ дедупликации.
        status: Состояние сообщения.
        attempt_count: Число завершенных попыток.
        max_attempts: Предел попыток.
        created_at: Время создания.
        queued_at: Время первой публикации.
        last_attempt_at: Время последней попытки.
        sent_at: Время успешной отправки.
        failed_at: Время окончательного отказа.
        next_attempt_at: Время следующей попытки.
        last_error_code: Последний код ошибки.
        last_error_message: Последнее описание ошибки.
    """

    __tablename__ = MESSAGES_TABLE
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'queued', 'sent', 'failed', 'cancelled')",
            name="ck_messages_status",
        ),
        CheckConstraint("template_version >= 1", name="ck_messages_template_version"),
        CheckConstraint("attempt_count >= 0", name="ck_messages_attempt_count"),
        CheckConstraint("max_attempts >= 1", name="ck_messages_max_attempts"),
        ForeignKeyConstraint(
            ["campaign_id"],
            [f"{NOTIFICATION_SCHEMA}.{CAMPAIGNS_TABLE}.id"],
            name="fk_messages_campaign",
            ondelete="CASCADE",
        ),
        Index("ix_messages_campaign", "campaign_id"),
        Index("ix_messages_status", "status"),
        Index("ix_messages_next_attempt", "next_attempt_at"),
        Index("ux_messages_idempotency", "idempotency_key", unique=True),
        {"schema": NOTIFICATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    campaign_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    debtor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    variables: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    recipient: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class MessageAttemptRow(Base):
    """Результат попытки отправки сообщения.

    Attributes:
        id: Идентификатор записи.
        message_id: Сообщение, к которому относится попытка.
        attempt_number: Номер попытки, начиная с 1.
        outcome: Результат попытки.
        occurred_at: Время результата.
        provider_message_id: Идентификатор письма провайдера.
        provider_error_code: Код ошибки провайдера.
    """

    __tablename__ = MESSAGE_ATTEMPTS_TABLE
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('sent', 'transient_failure', 'permanent_failure', 'rate_limited')",
            name="ck_message_attempts_outcome",
        ),
        CheckConstraint("attempt_number >= 1", name="ck_message_attempts_number"),
        ForeignKeyConstraint(
            ["message_id"],
            [f"{NOTIFICATION_SCHEMA}.{MESSAGES_TABLE}.id"],
            name="fk_message_attempts_message",
            ondelete="CASCADE",
        ),
        Index("ix_message_attempts_message", "message_id"),
        Index(
            "ux_message_attempts_number",
            "message_id",
            "attempt_number",
            unique=True,
        ),
        {"schema": NOTIFICATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    message_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
