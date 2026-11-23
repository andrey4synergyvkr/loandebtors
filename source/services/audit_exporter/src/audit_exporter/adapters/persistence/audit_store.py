"""Репозиторий append-only журнала аудита на SQLAlchemy."""

from datetime import UTC

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from audit_exporter.adapters.persistence.cursor import decode_cursor, encode_cursor
from audit_exporter.adapters.persistence.models import AuditRecordRow
from audit_exporter.domain import (
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditFilter,
    AuditOutcome,
    AuditPage,
    AuditRecord,
    CampaignId,
    Channel,
    ConflictError,
    MessageId,
)
from audit_exporter.ports.clock import Clock


class SqlAlchemyAuditStore:
    """Хранилище журнала аудита в схеме audit."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
    ) -> None:
        """Сохранить фабрику сессий и часы."""
        self._session_factory = session_factory
        self._clock = clock

    async def append(self, event: AuditEvent) -> None:
        """Записать событие, повтор по event_id не создаёт новую запись.

        Raises:
            ConflictError: Событие с таким event_id уже записано с другим содержимым.
        """
        statement = (
            pg_insert(AuditRecordRow)
            .values(
                event_id=event.event_id,
                occurred_at=event.occurred_at,
                service=event.service,
                actor_type=event.actor.type.value,
                actor_identifier=event.actor.identifier,
                action=event.action.value,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                campaign_id=event.campaign_id,
                message_id=event.message_id,
                channel=event.channel,
                outcome=event.outcome.value,
                details=dict(event.details),
                correlation_id=event.correlation_id,
                trace_id=event.trace_id,
                ingested_at=self._clock.now(),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
            .returning(AuditRecordRow.sequence)
        )
        async with self._session_factory() as session, session.begin():
            inserted = await session.scalar(statement)
            if inserted is not None:
                return
            existing = await session.scalar(
                select(AuditRecordRow).where(AuditRecordRow.event_id == event.event_id)
            )
            if existing is None:
                raise ConflictError(f"Событие {event.event_id} уже существует, но недоступно для сверки")
            if not _same_event(existing, event):
                raise ConflictError(f"Событие {event.event_id} уже записано с другим содержимым")

    async def query(self, filters: AuditFilter) -> AuditPage:
        """Вернуть страницу журнала с фильтрами и курсором."""
        statement = select(AuditRecordRow).order_by(AuditRecordRow.sequence)
        if filters.campaign_id is not None:
            statement = statement.where(AuditRecordRow.campaign_id == filters.campaign_id)
        if filters.channel is not None:
            statement = statement.where(AuditRecordRow.channel == filters.channel)
        if filters.action is not None:
            statement = statement.where(AuditRecordRow.action == filters.action.value)
        if filters.occurred_from is not None:
            statement = statement.where(AuditRecordRow.occurred_at >= filters.occurred_from)
        if filters.occurred_to is not None:
            statement = statement.where(AuditRecordRow.occurred_at < filters.occurred_to)
        if filters.cursor is not None:
            statement = statement.where(AuditRecordRow.sequence > decode_cursor(filters.cursor))
        statement = statement.limit(filters.limit + 1)

        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()

        has_next = len(rows) > filters.limit
        items = tuple(_to_record(row) for row in rows[: filters.limit])
        next_cursor = encode_cursor(items[-1].sequence) if has_next and items else None
        return AuditPage(items=items, next_cursor=next_cursor)

    async def get_by_event_id(self, event_id: AuditEventId) -> AuditRecord | None:
        """Вернуть запись по идентификатору события или None."""
        statement = select(AuditRecordRow).where(AuditRecordRow.event_id == event_id)
        async with self._session_factory() as session:
            row = await session.scalar(statement)
        if row is None:
            return None
        return _to_record(row)


def _same_event(row: AuditRecordRow, event: AuditEvent) -> bool:
    """Сравнить сохранённую запись с повторно доставленным событием."""
    return (
        row.occurred_at.astimezone(UTC) == event.occurred_at.astimezone(UTC)
        and row.service == event.service
        and row.actor_type == event.actor.type.value
        and row.actor_identifier == event.actor.identifier
        and row.action == event.action.value
        and row.entity_type == event.entity_type
        and row.entity_id == event.entity_id
        and row.campaign_id == event.campaign_id
        and row.message_id == event.message_id
        and row.channel == event.channel
        and row.outcome == event.outcome.value
        and {str(key): str(value) for key, value in (row.details or {}).items()} == dict(event.details)
        and row.correlation_id == event.correlation_id
        and row.trace_id == event.trace_id
    )


def _to_record(row: AuditRecordRow) -> AuditRecord:
    """Преобразовать ORM-запись в доменную запись журнала."""
    event = AuditEvent(
        event_id=AuditEventId(row.event_id),
        occurred_at=row.occurred_at,
        service=row.service,
        actor=AuditActor(
            type=AuditActorType(row.actor_type),
            identifier=row.actor_identifier,
        ),
        action=AuditAction(row.action),
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        campaign_id=CampaignId(row.campaign_id) if row.campaign_id is not None else None,
        message_id=MessageId(row.message_id) if row.message_id is not None else None,
        channel=Channel(row.channel) if row.channel is not None else None,
        outcome=AuditOutcome(row.outcome),
        details={str(key): str(value) for key, value in (row.details or {}).items()},
        correlation_id=row.correlation_id,
        trace_id=row.trace_id,
    )
    return AuditRecord(sequence=row.sequence, event=event, ingested_at=row.ingested_at)
