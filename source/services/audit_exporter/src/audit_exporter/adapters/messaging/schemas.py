"""Схемы входящих сообщений audit.event."""

from datetime import UTC
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from audit_exporter.domain import (
    CHANNEL_PATTERN,
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditOutcome,
    CampaignId,
    Channel,
    MessageId,
)


class AuditActorPayload(BaseModel):
    """Инициатор audit-события в сообщении RabbitMQ.

    Attributes:
        type: Тип инициатора.
        identifier: Логин сотрудника или имя сервиса.
    """

    model_config = ConfigDict(extra="forbid")

    type: AuditActorType
    identifier: str | None = Field(default=None, max_length=255)


class AuditEventPayload(BaseModel):
    """Тело сообщения audit.event по контракту AsyncAPI.

    Attributes:
        event_id: Уникальный идентификатор события.
        occurred_at: Время действия в сервисе-источнике.
        service: Источник события.
        actor: Инициатор действия.
        action: Выполненное действие.
        entity_type: Тип сущности.
        entity_id: Идентификатор сущности.
        campaign_id: Идентификатор кампании.
        message_id: Идентификатор сообщения.
        channel: Код канала.
        outcome: Результат действия.
        details: Дополнительные поля без персональных данных.
        correlation_id: Идентификатор сценария.
        trace_id: Идентификатор OTel-трейса.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    occurred_at: AwareDatetime
    service: str = Field(min_length=1, max_length=64)
    actor: AuditActorPayload
    action: AuditAction
    entity_type: str = Field(min_length=1, max_length=64)
    entity_id: str = Field(min_length=1, max_length=255)
    campaign_id: UUID | None = None
    message_id: UUID | None = None
    channel: str | None = Field(default=None, pattern=CHANNEL_PATTERN, max_length=64)
    outcome: AuditOutcome
    details: dict[str, str]
    correlation_id: str = Field(min_length=1, max_length=128)
    trace_id: str | None = Field(default=None, max_length=64)


def to_domain(payload: AuditEventPayload) -> AuditEvent:
    """Преобразовать тело сообщения в доменное событие."""
    return AuditEvent(
        event_id=AuditEventId(payload.event_id),
        occurred_at=payload.occurred_at.astimezone(UTC),
        service=payload.service,
        actor=AuditActor(type=payload.actor.type, identifier=payload.actor.identifier),
        action=payload.action,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        campaign_id=CampaignId(payload.campaign_id) if payload.campaign_id is not None else None,
        message_id=MessageId(payload.message_id) if payload.message_id is not None else None,
        channel=Channel(payload.channel) if payload.channel is not None else None,
        outcome=payload.outcome,
        details=dict(payload.details),
        correlation_id=payload.correlation_id,
        trace_id=payload.trace_id,
    )
