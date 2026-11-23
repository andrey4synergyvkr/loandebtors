"""Репозиторий outbox на SQLAlchemy."""

from datetime import datetime, timedelta
from math import pow

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from notifications.adapters.persistence.models import OutboxRow
from notifications.ports.outbox import OutboxBatchResult, OutboxEntry, PublishCallback

MAX_ERROR_LENGTH: int = 1000


class SqlAlchemyOutboxStore:
    """Выбирает готовые записи outbox и публикует их через callback."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        max_attempts: int,
        retry_base_seconds: float,
        retry_max_seconds: float,
    ) -> None:
        """Сохранить фабрику сессий и параметры повторов."""
        self._session_factory = session_factory
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds

    async def process_ready(
        self,
        limit: int,
        now: datetime,
        publish: PublishCallback,
    ) -> OutboxBatchResult:
        """Опубликовать пачку готовых записей и зафиксировать результат."""
        published = 0
        failed = 0
        async with self._session_factory() as session, session.begin():
            statement = (
                select(OutboxRow)
                .where(
                    OutboxRow.published_at.is_(None),
                    OutboxRow.failed_at.is_(None),
                    OutboxRow.available_at <= now,
                    OutboxRow.attempts < self._max_attempts,
                )
                .order_by(OutboxRow.available_at, OutboxRow.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            rows = (await session.scalars(statement)).all()
            for row in rows:
                entry = _to_entry(row)
                try:
                    await publish(entry)
                except Exception as exc:
                    row.attempts += 1
                    row.last_error = str(exc)[:MAX_ERROR_LENGTH]
                    row.available_at = now + timedelta(seconds=self._retry_delay_seconds(row.attempts))
                    failed += 1
                else:
                    row.published_at = now
                    row.last_error = None
                    published += 1
        return OutboxBatchResult(published=published, failed=failed)

    def _retry_delay_seconds(self, attempts: int) -> float:
        """Рассчитать экспоненциальную задержку публикации."""
        delay = self._retry_base_seconds * pow(2, max(0, attempts - 1))
        return min(float(delay), self._retry_max_seconds)


def _to_entry(row: OutboxRow) -> OutboxEntry:
    """Преобразовать ORM-запись в DTO порта."""
    return OutboxEntry(
        id=row.id,
        event_type=row.event_type,
        exchange=row.exchange,
        routing_key=row.routing_key,
        payload=row.payload,
        headers=row.headers,
        occurred_at=row.occurred_at,
        available_at=row.available_at,
        attempts=row.attempts,
    )
