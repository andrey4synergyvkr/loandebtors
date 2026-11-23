"""Репозиторий попыток отправки."""

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from email_channel.adapters.persistence.models import SendAttemptRow
from email_channel.domain import MessageId, SendAttempt


class SqlAlchemySendAttemptRepository:
    """Хранит попытки отправки в схеме email_channel."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def add(self, attempt: SendAttempt) -> None:
        """Добавить запись о попытке."""
        self._session.add(
            SendAttemptRow(
                id=uuid4(),
                message_id=attempt.message_id,
                attempt_number=attempt.attempt_number,
                recipient=attempt.recipient,
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
                outcome=attempt.outcome.value if attempt.outcome is not None else None,
                provider_message_id=attempt.provider_message_id,
                provider_error_code=attempt.provider_error_code,
                provider_error_message=attempt.provider_error_message,
            )
        )

    async def count_by_message(self, message_id: MessageId) -> int:
        """Вернуть число попыток сообщения."""
        statement = (
            select(func.count()).select_from(SendAttemptRow).where(SendAttemptRow.message_id == message_id)
        )
        total = await self._session.scalar(statement)
        return int(total or 0)
