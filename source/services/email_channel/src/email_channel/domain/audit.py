"""Контракт audit-события, который публикует Email Channel."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from email_channel.domain.enums import AuditAction, AuditActorType, AuditOutcome
from email_channel.domain.ids import AuditEventId, CampaignId, Channel, MessageId

EMAIL_CHANNEL_SERVICE: Final = "email_channel"
CHANNEL_ENTITY_TYPE: Final = "channel"
SMTP_ENTITY_ID: Final = "smtp"


@dataclass(frozen=True, slots=True)
class AuditActor:
    """Инициатор audit-события.

    Attributes:
        type: Тип инициатора.
        identifier: Логин сотрудника или имя сервиса.
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
        entity_id: Идентификатор сущности.
        campaign_id: Идентификатор кампании.
        message_id: Идентификатор сообщения.
        channel: Код канала.
        outcome: Результат действия.
        details: Дополнительные поля без персональных данных.
        correlation_id: Идентификатор сценария.
        trace_id: Идентификатор OTel-трейса.
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
