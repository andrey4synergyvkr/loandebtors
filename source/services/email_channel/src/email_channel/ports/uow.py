"""Порт единицы работы Email Channel."""

from types import TracebackType
from typing import Protocol, Self

from email_channel.ports.attempts import SendAttemptRepository
from email_channel.ports.audit import AuditEventOutbox
from email_channel.ports.config import ChannelConfigRepository
from email_channel.ports.processed import ProcessedMessageRepository
from email_channel.ports.results import MessageResultOutbox
from email_channel.ports.templates import EmailTemplateRepository


class UnitOfWork(Protocol):
    """Транзакция, в которой состояние и outbox фиксируются вместе."""

    config: ChannelConfigRepository
    templates: EmailTemplateRepository
    attempts: SendAttemptRepository
    processed: ProcessedMessageRepository
    results: MessageResultOutbox
    audit: AuditEventOutbox

    async def __aenter__(self) -> Self:
        """Открыть единицу работы."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Закрыть единицу работы."""
        ...

    async def commit(self) -> None:
        """Зафиксировать изменения."""
        ...


class UnitOfWorkFactory(Protocol):
    """Фабрика единиц работы."""

    def __call__(self) -> UnitOfWork:
        """Вернуть новую единицу работы."""
        ...
