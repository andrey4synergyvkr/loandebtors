"""Репозиторий идемпотентности сообщений."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from email_channel.adapters.persistence.models import ProcessedMessageRow
from email_channel.domain import MessageId


class SqlAlchemyProcessedMessageRepository:
    """Хранит идентификаторы уже обработанных сообщений."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def is_processed(self, message_id: MessageId) -> bool:
        """Проверить, обработано ли сообщение."""
        statement = select(ProcessedMessageRow.message_id).where(ProcessedMessageRow.message_id == message_id)
        return await self._session.scalar(statement) is not None

    async def mark_processed(self, message_id: MessageId, processed_at: datetime) -> bool:
        """Отметить сообщение обработанным и вернуть True при первой обработке."""
        statement = (
            pg_insert(ProcessedMessageRow)
            .values(message_id=message_id, processed_at=processed_at)
            .on_conflict_do_nothing(index_elements=["message_id"])
            .returning(ProcessedMessageRow.message_id)
        )
        result = await self._session.scalar(statement)
        return result is not None
