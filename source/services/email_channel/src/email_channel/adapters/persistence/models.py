"""SQLAlchemy-модели инфраструктуры Email Channel."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMAIL_CHANNEL_SCHEMA: str = "email_channel"
OUTBOX_TABLE: str = "outbox"
SMTP_CONFIG_TABLE: str = "smtp_config"
EMAIL_TEMPLATES_TABLE: str = "email_templates"
SEND_ATTEMPTS_TABLE: str = "send_attempts"
PROCESSED_MESSAGES_TABLE: str = "processed_messages"


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
        {"schema": EMAIL_CHANNEL_SCHEMA},
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


class SmtpConfigRow(Base):
    """Настройки SMTP-адаптера.

    Attributes:
        id: Идентификатор единственной строки настроек.
        host: SMTP-хост провайдера.
        port: Порт SMTP.
        username: Учетная запись провайдера.
        password_ref: Ссылка на секрет.
        from_address: Адрес отправителя.
        from_name: Отображаемое имя отправителя.
        use_starttls: Включает STARTTLS.
        timeout_seconds: Таймаут SMTP-операции.
        rate_limit_per_second: Глобальный лимит писем в секунду.
        enabled: Выключенный канал не принимает новые отправки.
        updated_at: Время последнего изменения.
    """

    __tablename__ = SMTP_CONFIG_TABLE
    __table_args__ = ({"schema": EMAIL_CHANNEL_SCHEMA},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    from_address: Mapped[str] = mapped_column(String(320), nullable=False)
    from_name: Mapped[str] = mapped_column(String(200), nullable=False)
    use_starttls: Mapped[bool] = mapped_column(Boolean, nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    rate_limit_per_second: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmailTemplateRow(Base):
    """Email-вариант логического шаблона.

    Attributes:
        key: Логический ключ шаблона.
        version: Версия канального варианта.
        locale: Язык и регион.
        subject_template: Jinja2-шаблон темы.
        html_template: Jinja2-шаблон HTML-части.
        plain_text_template: Jinja2-шаблон текстовой части.
        required_variables: Обязательные переменные.
        updated_at: Время последнего изменения.
    """

    __tablename__ = EMAIL_TEMPLATES_TABLE
    __table_args__ = ({"schema": EMAIL_CHANNEL_SCHEMA},)

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    locale: Mapped[str] = mapped_column(String(10), primary_key=True)
    subject_template: Mapped[str] = mapped_column(Text, nullable=False)
    html_template: Mapped[str] = mapped_column(Text, nullable=False)
    plain_text_template: Mapped[str] = mapped_column(Text, nullable=False)
    required_variables: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SendAttemptRow(Base):
    """Попытка отправки письма.

    Attributes:
        id: Идентификатор попытки.
        message_id: Сообщение, к которому относится попытка.
        attempt_number: Номер попытки.
        recipient: Получатель письма.
        started_at: Время начала попытки.
        finished_at: Время завершения попытки.
        outcome: Результат попытки.
        provider_message_id: Идентификатор письма у провайдера.
        provider_error_code: Код ошибки провайдера.
        provider_error_message: Описание ошибки.
    """

    __tablename__ = SEND_ATTEMPTS_TABLE
    __table_args__ = (
        UniqueConstraint("message_id", "attempt_number", name="uq_send_attempt_message"),
        Index("ix_send_attempt_message", "message_id"),
        {"schema": EMAIL_CHANNEL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    message_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProcessedMessageRow(Base):
    """Сообщение, уже обработанное Email Channel.

    Attributes:
        message_id: Идентификатор сообщения.
        processed_at: Время обработки.
    """

    __tablename__ = PROCESSED_MESSAGES_TABLE
    __table_args__ = ({"schema": EMAIL_CHANNEL_SCHEMA},)

    message_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
