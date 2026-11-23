"""Порт идемпотентности обработанных сообщений."""

from datetime import datetime
from typing import Protocol

from email_channel.domain import MessageId


class ProcessedMessageRepository(Protocol):
    """Хранит идентификаторы уже обработанных сообщений."""

    async def is_processed(self, message_id: MessageId) -> bool:
        """Проверить, обработано ли сообщение."""
        ...

    async def mark_processed(self, message_id: MessageId, processed_at: datetime) -> bool:
        """Отметить сообщение обработанным и вернуть True при первой обработке."""
        ...
