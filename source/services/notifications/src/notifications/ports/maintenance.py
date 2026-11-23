"""Порт обслуживания: retention и восстановление зависших состояний."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from notifications.domain import Campaign, NotificationMessage


@dataclass(frozen=True, slots=True)
class ExhaustedMessageCommand:
    """Команда message.send, исчерпавшая попытки публикации.

    Attributes:
        outbox_id: Идентификатор записи outbox.
        message_id: Идентификатор сообщения из payload.
    """

    outbox_id: UUID
    message_id: UUID


class MaintenanceStore(Protocol):
    """Запросы и удаления для фонового обслуживания."""

    async def delete_published_outbox_before(self, cutoff: datetime) -> int:
        """Удалить опубликованные записи outbox старше cutoff."""
        ...

    async def delete_attempts_before(self, cutoff: datetime) -> int:
        """Удалить попытки отправки старше cutoff."""
        ...

    async def list_retry_due(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[NotificationMessage]:
        """Вернуть сообщения, у которых наступило время повтора."""
        ...

    async def list_stuck_campaigns(
        self,
        before: datetime,
        limit: int,
    ) -> Sequence[Campaign]:
        """Вернуть running-кампании без созданных сообщений."""
        ...

    async def list_completable_campaigns(self, limit: int) -> Sequence[Campaign]:
        """Вернуть running-кампании без незавершенных сообщений."""
        ...

    async def list_exhausted_message_send(
        self,
        max_attempts: int,
        limit: int,
    ) -> Sequence[ExhaustedMessageCommand]:
        """Вернуть команды message.send с исчерпанными попытками outbox."""
        ...

    async def mark_outbox_failed(self, outbox_id: UUID, failed_at: datetime) -> bool:
        """Зафиксировать окончательный отказ публикации записи outbox."""
        ...
