"""Порт единицы работы с репозиториями и outbox."""

from types import TracebackType
from typing import Protocol, Self

from notifications.ports.audit import AuditEventOutbox
from notifications.ports.maintenance import MaintenanceStore
from notifications.ports.outbox import CampaignEventOutbox, MessageCommandOutbox
from notifications.ports.repositories import (
    CampaignRepository,
    DebtorSnapshotRepository,
    MessageAttemptRepository,
    NotificationMessageRepository,
    NotificationTemplateRepository,
)


class UnitOfWork(Protocol):
    """Транзакционная граница состояния и исходящих событий.

    Attributes:
        campaigns: Репозиторий кампаний.
        templates: Репозиторий логических шаблонов.
        snapshots: Репозиторий снимков должников.
        messages: Репозиторий сообщений.
        attempts: Репозиторий попыток отправки.
        maintenance: Запросы retention и восстановления.
        events: Запись событий кампании в outbox.
        message_commands: Запись команд message.send в outbox.
        audit: Запись audit-событий в outbox.
    """

    campaigns: CampaignRepository
    templates: NotificationTemplateRepository
    snapshots: DebtorSnapshotRepository
    messages: NotificationMessageRepository
    attempts: MessageAttemptRepository
    maintenance: MaintenanceStore
    events: CampaignEventOutbox
    message_commands: MessageCommandOutbox
    audit: AuditEventOutbox

    async def __aenter__(self) -> Self:
        """Открыть сессию и транзакцию."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Откатить незавершённую транзакцию и закрыть сессию."""
        ...

    async def commit(self) -> None:
        """Зафиксировать состояние и outbox одной транзакцией."""
        ...


class UnitOfWorkFactory(Protocol):
    """Создаёт новую единицу работы на один сценарий."""

    def __call__(self) -> UnitOfWork:
        """Вернуть новую единицу работы."""
        ...
