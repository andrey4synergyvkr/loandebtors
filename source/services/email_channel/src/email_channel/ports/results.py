"""Порт публикации результатов доставки."""

from typing import Protocol

from email_channel.domain import MessageFailed, MessageSent


class MessageResultOutbox(Protocol):
    """Запись message.sent и message.failed в транзакционный outbox."""

    async def add_sent(
        self,
        event: MessageSent,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Добавить результат успешной отправки."""
        ...

    async def add_failed(
        self,
        event: MessageFailed,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Добавить результат неудачной отправки."""
        ...
