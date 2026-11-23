"""Единица работы на SQLAlchemy."""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction, async_sessionmaker

from notifications.adapters.persistence.attempts import SqlAlchemyMessageAttemptRepository
from notifications.adapters.persistence.audit_outbox import SqlAlchemyAuditOutbox
from notifications.adapters.persistence.campaign_events import SqlAlchemyCampaignEventOutbox
from notifications.adapters.persistence.campaigns import SqlAlchemyCampaignRepository
from notifications.adapters.persistence.maintenance import SqlAlchemyMaintenanceStore
from notifications.adapters.persistence.message_events import SqlAlchemyMessageCommandOutbox
from notifications.adapters.persistence.messages import SqlAlchemyNotificationMessageRepository
from notifications.adapters.persistence.snapshots import SqlAlchemyDebtorSnapshotRepository
from notifications.adapters.persistence.templates import SqlAlchemyTemplateRepository
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


class SqlAlchemyUnitOfWork:
    """Открывает сессию и транзакцию на один сценарий."""

    campaigns: CampaignRepository
    templates: NotificationTemplateRepository
    snapshots: DebtorSnapshotRepository
    messages: NotificationMessageRepository
    attempts: MessageAttemptRepository
    maintenance: MaintenanceStore
    events: CampaignEventOutbox
    message_commands: MessageCommandOutbox
    audit: AuditEventOutbox

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Сохранить фабрику сессий."""
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._transaction: AsyncSessionTransaction | None = None

    async def __aenter__(self) -> Self:
        """Открыть сессию и транзакцию, создать репозитории."""
        session = self._session_factory()
        transaction = session.begin()
        await transaction.__aenter__()
        self._session = session
        self._transaction = transaction
        self.campaigns = SqlAlchemyCampaignRepository(session)
        self.templates = SqlAlchemyTemplateRepository(session)
        self.snapshots = SqlAlchemyDebtorSnapshotRepository(session)
        self.messages = SqlAlchemyNotificationMessageRepository(session)
        self.attempts = SqlAlchemyMessageAttemptRepository(session)
        self.maintenance = SqlAlchemyMaintenanceStore(session)
        self.events = SqlAlchemyCampaignEventOutbox(session)
        self.message_commands = SqlAlchemyMessageCommandOutbox(session)
        self.audit = SqlAlchemyAuditOutbox(session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Откатить незавершённую транзакцию и закрыть сессию."""
        try:
            transaction = self._transaction
            if transaction is not None and transaction.is_active:
                await transaction.rollback()
        finally:
            session = self._session
            self._transaction = None
            self._session = None
            if session is not None:
                await session.close()

    async def commit(self) -> None:
        """Зафиксировать состояние и outbox одной транзакцией."""
        transaction = self._transaction
        if transaction is None:
            raise RuntimeError("Единица работы не открыта")
        await transaction.commit()


class SqlAlchemyUnitOfWorkFactory:
    """Создаёт единицы работы поверх фабрики сессий."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Сохранить фабрику сессий."""
        self._session_factory = session_factory

    def __call__(self) -> SqlAlchemyUnitOfWork:
        """Вернуть новую единицу работы."""
        return SqlAlchemyUnitOfWork(self._session_factory)
