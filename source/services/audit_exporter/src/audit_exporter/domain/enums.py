"""Статусы и классификаторы журнала аудита."""

from enum import StrEnum


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
