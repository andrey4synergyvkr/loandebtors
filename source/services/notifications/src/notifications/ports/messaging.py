"""Порты публикации сообщений в RabbitMQ."""

from typing import Protocol

from notifications.domain import CampaignScheduled, NotificationCommand


class CampaignScheduledPublisher(Protocol):
    """Публикация события campaign.scheduled."""

    async def publish(self, event: CampaignScheduled) -> None:
        """Опубликовать событие после фиксации расписания в БД."""
        ...


class NotificationCommandPublisher(Protocol):
    """Публикация команды message.send."""

    async def publish(self, command: NotificationCommand) -> None:
        """Опубликовать команду через publisher confirms."""
        ...
