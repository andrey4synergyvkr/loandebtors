"""Порт репозитория попыток отправки."""

from typing import Protocol

from email_channel.domain import MessageId, SendAttempt


class SendAttemptRepository(Protocol):
    """Доступ к истории попыток отправки."""

    async def add(self, attempt: SendAttempt) -> None:
        """Добавить запись о попытке."""
        ...

    async def count_by_message(self, message_id: MessageId) -> int:
        """Вернуть число завершённых попыток сообщения."""
        ...
