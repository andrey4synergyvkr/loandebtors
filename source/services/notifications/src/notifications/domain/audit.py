"""Контракт audit-события, который пишет Notifications."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from notifications.domain.ids import AuditEventId, CampaignId, Channel, MessageId


class AuditActorType(StrEnum):
    """Тип инициатора действия.

    Attributes:
        OPERATOR: Сотрудник, управляющий кампанией.
        ADMINISTRATOR: Сотрудник, настраивающий канал или выгружающий аудит.
        SYSTEM: Событие сервиса без участия пользователя.
    """

    OPERATOR = "operator"
    ADMINISTRATOR = "administrator"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class AuditActor:
    """Инициатор audit-события.

    Attributes:
        type: Тип инициатора.
        identifier: Логин сотрудника или имя сервиса, если известны.
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
    """Словарь действий журнала аудита.

    Attributes:
        CAMPAIGN_CREATED: Кампания создана.
        CAMPAIGN_UPDATED: Кампания изменена.
        CAMPAIGN_SCHEDULED: Кампания поставлена в расписание.
        CAMPAIGN_STARTED: Кампания запущена.
        CAMPAIGN_COMPLETED: Кампания завершена.
        CAMPAIGN_CANCELLED: Кампания отменена.
        CAMPAIGN_FAILED: Кампания завершилась ошибкой.
        TEMPLATE_CREATED: Создана версия логического шаблона.
        TEMPLATE_STATUS_CHANGED: Изменён статус версии логического шаблона.
        MESSAGE_QUEUED: Сообщение поставлено в очередь.
        MESSAGE_SENT: Провайдер принял сообщение.
        MESSAGE_FAILED: Отправка сообщения завершилась ошибкой.
        CHANNEL_CONFIG_UPDATED: Настройки канала изменены.
        AUDIT_EXPORTED: Журнал аудита выгружен.
    """

    CAMPAIGN_CREATED = "campaign.created"
    CAMPAIGN_UPDATED = "campaign.updated"
    CAMPAIGN_SCHEDULED = "campaign.scheduled"
    CAMPAIGN_STARTED = "campaign.started"
    CAMPAIGN_COMPLETED = "campaign.completed"
    CAMPAIGN_CANCELLED = "campaign.cancelled"
    CAMPAIGN_FAILED = "campaign.failed"
    TEMPLATE_CREATED = "template.created"
    TEMPLATE_STATUS_CHANGED = "template.status.changed"
    MESSAGE_QUEUED = "message.queued"
    MESSAGE_SENT = "message.sent"
    MESSAGE_FAILED = "message.failed"
    CHANNEL_CONFIG_UPDATED = "channel.config.updated"
    AUDIT_EXPORTED = "audit.exported"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Событие для append-only журнала аудита.

    Attributes:
        event_id: Уникальный идентификатор события.
        occurred_at: Время действия в сервисе-источнике.
        service: Источник: notifications, scheduler или email_channel.
        actor: Инициатор действия.
        action: Выполненное действие.
        entity_type: Тип сущности: campaign, message или channel.
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
