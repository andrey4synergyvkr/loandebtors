"""Запись audit-событий Email Channel в outbox."""

from datetime import UTC
from typing import Final
from uuid import uuid4

from opentelemetry import propagate
from sqlalchemy.ext.asyncio import AsyncSession

from email_channel.adapters.messaging.constants import EVENTS_EXCHANGE, RoutingKey
from email_channel.adapters.persistence.models import OutboxRow
from email_channel.domain import AuditEvent

MAX_DETAILS_LENGTH: Final = 1000


class SqlAlchemyAuditOutbox:
    """Добавляет audit.event в outbox текущей сессии."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def add(self, event: AuditEvent) -> None:
        """Записать событие в outbox без публикации в RabbitMQ."""
        occurred_at = event.occurred_at.astimezone(UTC)
        headers: dict[str, str] = {"correlation_id": event.correlation_id}
        if event.trace_id is not None:
            headers["trace_id"] = event.trace_id
        propagate.inject(headers)
        row = OutboxRow(
            id=uuid4(),
            event_type=RoutingKey.AUDIT_EVENT.value,
            exchange=EVENTS_EXCHANGE,
            routing_key=RoutingKey.AUDIT_EVENT.value,
            payload={
                "event_id": str(event.event_id),
                "occurred_at": occurred_at.isoformat(),
                "service": event.service,
                "actor": {
                    "type": event.actor.type.value,
                    "identifier": event.actor.identifier,
                },
                "action": event.action.value,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "campaign_id": str(event.campaign_id) if event.campaign_id is not None else None,
                "message_id": str(event.message_id) if event.message_id is not None else None,
                "channel": event.channel,
                "outcome": event.outcome.value,
                "details": {key: value[:MAX_DETAILS_LENGTH] for key, value in event.details.items()},
                "correlation_id": event.correlation_id,
                "trace_id": event.trace_id,
            },
            headers=headers,
            occurred_at=occurred_at,
            available_at=occurred_at,
            attempts=0,
        )
        self._session.add(row)
