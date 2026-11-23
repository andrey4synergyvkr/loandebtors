"""Единица работы на SQLAlchemy."""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction, async_sessionmaker

from email_channel.adapters.persistence.attempts import SqlAlchemySendAttemptRepository
from email_channel.adapters.persistence.audit_outbox import SqlAlchemyAuditOutbox
from email_channel.adapters.persistence.channel_config import SqlAlchemyChannelConfigRepository
from email_channel.adapters.persistence.processed import SqlAlchemyProcessedMessageRepository
from email_channel.adapters.persistence.results import SqlAlchemyMessageResultOutbox
from email_channel.adapters.persistence.templates import SqlAlchemyEmailTemplateRepository
from email_channel.ports.attempts import SendAttemptRepository
from email_channel.ports.audit import AuditEventOutbox
from email_channel.ports.config import ChannelConfigRepository
from email_channel.ports.processed import ProcessedMessageRepository
from email_channel.ports.results import MessageResultOutbox
from email_channel.ports.templates import EmailTemplateRepository
from email_channel.ports.uow import UnitOfWork


class SqlAlchemyUnitOfWork:
    """Открывает сессию и транзакцию на один сценарий."""

    config: ChannelConfigRepository
    templates: EmailTemplateRepository
    attempts: SendAttemptRepository
    processed: ProcessedMessageRepository
    results: MessageResultOutbox
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
        self.config = SqlAlchemyChannelConfigRepository(session)
        self.templates = SqlAlchemyEmailTemplateRepository(session)
        self.attempts = SqlAlchemySendAttemptRepository(session)
        self.processed = SqlAlchemyProcessedMessageRepository(session)
        self.results = SqlAlchemyMessageResultOutbox(session)
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
        """Зафиксировать настройки и outbox одной транзакцией."""
        transaction = self._transaction
        if transaction is None:
            raise RuntimeError("Единица работы не открыта")
        await transaction.commit()


class SqlAlchemyUnitOfWorkFactory:
    """Создаёт единицы работы поверх фабрики сессий."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Сохранить фабрику сессий."""
        self._session_factory = session_factory

    def __call__(self) -> UnitOfWork:
        """Вернуть новую единицу работы."""
        return SqlAlchemyUnitOfWork(self._session_factory)
