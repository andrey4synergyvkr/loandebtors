"""Pydantic-схемы ответов Audit Export API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from audit_exporter.domain import (
    AuditAction,
    AuditActorType,
    AuditEvent,
    AuditOutcome,
    AuditPage,
    AuditRecord,
)


class AuditActorResponse(BaseModel):
    """Инициатор audit-события в ответе API.

    Attributes:
        type: Тип инициатора.
        identifier: Логин сотрудника или имя сервиса.
    """

    model_config = ConfigDict(extra="forbid")

    type: AuditActorType
    identifier: str | None = None


class AuditEventResponse(BaseModel):
    """Audit-событие в ответе API.

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
    occurred_at: datetime
    service: str
    actor: AuditActorResponse
    action: AuditAction
    entity_type: str
    entity_id: str
    campaign_id: UUID | None = None
    message_id: UUID | None = None
    channel: str | None = None
    outcome: AuditOutcome
    details: dict[str, str]
    correlation_id: str
    trace_id: str | None = None


class AuditRecordResponse(BaseModel):
    """Запись журнала в ответе API.

    Attributes:
        sequence: Порядковый номер записи.
        event: Исходное событие.
        ingested_at: Время записи в журнал.
    """

    model_config = ConfigDict(extra="forbid")

    sequence: int
    event: AuditEventResponse
    ingested_at: datetime


class AuditPageResponse(BaseModel):
    """Страница журнала в ответе API.

    Attributes:
        items: Записи текущей страницы.
        next_cursor: Курсор следующей страницы или None.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[AuditRecordResponse]
    next_cursor: str | None


def event_to_response(event: AuditEvent) -> AuditEventResponse:
    """Преобразовать доменное событие в схему ответа."""
    return AuditEventResponse(
        event_id=event.event_id,
        occurred_at=event.occurred_at,
        service=event.service,
        actor=AuditActorResponse(
            type=event.actor.type,
            identifier=event.actor.identifier,
        ),
        action=event.action,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        campaign_id=event.campaign_id,
        message_id=event.message_id,
        channel=event.channel,
        outcome=event.outcome,
        details=dict(event.details),
        correlation_id=event.correlation_id,
        trace_id=event.trace_id,
    )


def record_to_response(record: AuditRecord) -> AuditRecordResponse:
    """Преобразовать доменную запись в схему ответа."""
    return AuditRecordResponse(
        sequence=record.sequence,
        event=event_to_response(record.event),
        ingested_at=record.ingested_at,
    )


def page_to_response(page: AuditPage) -> AuditPageResponse:
    """Преобразовать доменную страницу в схему ответа."""
    return AuditPageResponse(
        items=[record_to_response(record) for record in page.items],
        next_cursor=page.next_cursor,
    )
