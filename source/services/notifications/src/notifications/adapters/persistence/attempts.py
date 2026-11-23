"""Репозиторий попыток отправки на SQLAlchemy."""

from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from notifications.adapters.persistence.models import MessageAttemptRow
from notifications.domain import (
    ConflictError,
    DeliveryOutcome,
    MessageAttempt,
    MessageId,
)


class SqlAlchemyMessageAttemptRepository:
    """Хранит результаты попыток отправки сообщений."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def add(self, attempt: MessageAttempt) -> None:
        """Добавить запись результата попытки.

        Raises:
            ConflictError: Попытка с таким номером уже записана.
        """
        self._session.add(
            MessageAttemptRow(
                id=uuid4(),
                message_id=attempt.message_id,
                attempt_number=attempt.attempt_number,
                outcome=attempt.outcome.value,
                occurred_at=attempt.occurred_at,
                provider_message_id=attempt.provider_message_id,
                provider_error_code=attempt.provider_error_code,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError(
                f"Попытка {attempt.attempt_number} сообщения {attempt.message_id} уже записана"
            ) from exc

    async def list_by_message(self, message_id: MessageId) -> Sequence[MessageAttempt]:
        """Вернуть историю попыток сообщения."""
        statement = (
            select(MessageAttemptRow)
            .where(MessageAttemptRow.message_id == message_id)
            .order_by(MessageAttemptRow.attempt_number)
        )
        rows = (await self._session.scalars(statement)).all()
        return [_to_domain(row) for row in rows]


def _to_domain(row: MessageAttemptRow) -> MessageAttempt:
    """Преобразовать ORM-запись в доменную попытку."""
    return MessageAttempt(
        message_id=MessageId(UUID(str(row.message_id))),
        attempt_number=row.attempt_number,
        outcome=DeliveryOutcome(row.outcome),
        occurred_at=row.occurred_at,
        provider_message_id=row.provider_message_id,
        provider_error_code=row.provider_error_code,
    )
