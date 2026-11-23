"""Контракт audit-события для append-only журнала."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from audit_exporter.domain.enums import AuditAction, AuditActorType, AuditOutcome
from audit_exporter.domain.ids import AuditEventId, CampaignId, Channel, MessageId

CHANNEL_PATTERN: Final = r"^[a-z][a-z0-9_-]*$"
AUDIT_EXPORTER_SERVICE: Final = "audit_exporter"
AUDIT_ENTITY_TYPE: Final = "audit"
AUDIT_RECORDS_ENTITY_ID: Final = "audit-records"


@dataclass(frozen=True, slots=True)
class AuditActor:
    """Инициатор audit-события.

    Attributes:
        type: Тип инициатора.
        identifier: Логин сотрудника или имя сервиса, если известны.
    """

    type: AuditActorType
    identifier: str | None


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Событие для append-only журнала аудита.

    Attributes:
        event_id: Уникальный идентификатор события.
        occurred_at: Время действия в сервисе-источнике.
        service: Источник события.
        actor: Инициатор действия.
        action: Выполненное действие.
        entity_type: Тип сущности.
        entity_id: Идентификатор сущности в исходном сервисе.
        campaign_id: Заполняется для событий кампании и сообщений.
        message_id: Заполняется для событий сообщений.
        channel: Заполняется для событий канала.
        outcome: Результат действия.
        details: Дополнительные поля без персональных данных.
        correlation_id: Связывает события одного сценария.
        trace_id: Идентификатор OTel-трейса, если он есть.
    """

    event_id: AuditEventId
    occurred_at: datetime
    service: str
    actor: AuditActor
    action: AuditAction
    entity_type: str
    entity_id: str
    campaign_id: CampaignId | None
    message_id: MessageId | None
    channel: Channel | None
    outcome: AuditOutcome
    details: Mapping[str, str]
    correlation_id: str
    trace_id: str | None
