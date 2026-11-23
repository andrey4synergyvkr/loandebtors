"""Статусы домена Notifications."""

from enum import StrEnum


class CampaignStatus(StrEnum):
    """Состояние жизненного цикла кампании.

    Attributes:
        DRAFT: Создана, выборка и запуск не выполнялись.
        SCHEDULED: Ожидает запуска по расписанию.
        RUNNING: Выборка завершена, сообщения создаются и отправляются.
        COMPLETED: Обработка сообщений завершена.
        CANCELLED: Остановлена оператором.
        FAILED: Выборка или запуск завершились ошибкой.
    """

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TemplateStatus(StrEnum):
    """Доступность версии логического шаблона.

    Attributes:
        DRAFT: Еще не используется кампаниями.
        ACTIVE: Доступен для новых кампаний.
        ARCHIVED: Сохранен для истории, новые отправки не используют.
    """

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class MessageStatus(StrEnum):
    """Состояние сообщения кампании.

    Attributes:
        PENDING: Ожидает постановки в очередь.
        QUEUED: Команда опубликована в message.send.
        SENT: Провайдер принял письмо, факт доставки не подтвержден.
        FAILED: Постоянная ошибка или исчерпаны попытки.
        CANCELLED: Отменено из-за остановки кампании.
    """

    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"
