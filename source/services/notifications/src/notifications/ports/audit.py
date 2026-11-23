"""Порт записи audit-событий в outbox."""

from typing import Protocol

from notifications.domain import AuditEvent


class AuditEventOutbox(Protocol):
    """Запись audit-событий в транзакции сервиса."""

    async def add(self, event: AuditEvent) -> None:
        """Записать событие в outbox без публикации в RabbitMQ."""
        ...
