"""Контракт audit-события, который пишет Scheduler."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from scheduler.domain.ids import AuditEventId, CampaignId


class AuditActorType(StrEnum):
    """Тип инициатора действия.

    Attributes:
        SYSTEM: Событие сервиса без участия пользователя.
    """

    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class AuditActor:
    """Инициатор audit-события.

    Attributes:
        type: Тип инициатора.
        identifier: Имя сервиса, если известно.
    """

    type: AuditActorType
    identifier: str | None


class AuditOutcome(StrEnum):
    """Результат действия.

    Attributes:
        SUCCESS: Действие завершилось успешно.
        FAILURE: Действие завершилось ошибкой.
    """

    SUCCESS = "success"
    FAILURE = "failure"


class AuditAction(StrEnum):
    """Действия планировщика в журнале аудита.

    Attributes:
        CAMPAIGN_SCHEDULED: Кампания поставлена в расписание.
        CAMPAIGN_STARTED: Кампания запущена по расписанию.
        CAMPAIGN_CANCELLED: Расписание кампании снято.
    """

    CAMPAIGN_SCHEDULED = "campaign.scheduled"
    CAMPAIGN_STARTED = "campaign.started"
    CAMPAIGN_CANCELLED = "campaign.cancelled"


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
        campaign_id: Идентификатор кампании.
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
    outcome: AuditOutcome
    details: Mapping[str, str]
    correlation_id: str
    trace_id: str | None
