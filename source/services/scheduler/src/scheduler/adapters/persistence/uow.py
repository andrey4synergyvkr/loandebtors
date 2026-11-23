"""Единица работы на SQLAlchemy."""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction, async_sessionmaker

from scheduler.adapters.persistence.cancellations import SqlAlchemyCancelledCampaignRepository
from scheduler.adapters.persistence.event_outbox import SqlAlchemyEventOutbox
from scheduler.adapters.persistence.schedules import SqlAlchemyCampaignScheduleRepository
from scheduler.ports.outbox import EventOutbox
from scheduler.ports.repositories import CampaignScheduleRepository, CancelledCampaignRepository


class SqlAlchemyUnitOfWork:
    """Открывает сессию и транзакцию на один сценарий."""

    schedules: CampaignScheduleRepository
    cancellations: CancelledCampaignRepository
    outbox: EventOutbox

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Сохранить фабрику сессий."""
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._transaction: AsyncSessionTransaction | None = None

    async def __aenter__(self) -> Self:
        """Открыть сессию и транзакцию, создать адаптеры."""
        session = self._session_factory()
        transaction = session.begin()
        await transaction.__aenter__()
        self._session = session
        self._transaction = transaction
        self.schedules = SqlAlchemyCampaignScheduleRepository(session)
        self.cancellations = SqlAlchemyCancelledCampaignRepository(session)
        self.outbox = SqlAlchemyEventOutbox(session)
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
