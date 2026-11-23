"""Запись исходящих событий Scheduler в outbox текущей транзакции."""

from datetime import UTC
from typing import Final
from uuid import uuid4

from opentelemetry import propagate
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.adapters.messaging.constants import EVENTS_EXCHANGE, RoutingKey
from scheduler.adapters.persistence.models import OutboxRow
from scheduler.domain.audit import AuditEvent
from scheduler.domain.events import CampaignStart

MAX_DETAILS_LENGTH: Final = 1000


class SqlAlchemyEventOutbox:
    """Добавляет campaign.start и audit.event в outbox текущей сессии."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def add_campaign_start(
        self,
        event: CampaignStart,
        *,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Добавить команду запуска кампании."""
        occurred_at = event.occurred_at.astimezone(UTC)
        headers: dict[str, str] = {"correlation_id": correlation_id}
        if trace_id is not None:
            headers["trace_id"] = trace_id
        propagate.inject(headers)
        row = OutboxRow(
            id=uuid4(),
            event_type=RoutingKey.CAMPAIGN_START.value,
            exchange=EVENTS_EXCHANGE,
            routing_key=RoutingKey.CAMPAIGN_START.value,
            payload={
                "campaign_id": str(event.campaign_id),
                "scheduled_for": event.scheduled_for.astimezone(UTC).isoformat(),
                "occurred_at": occurred_at.isoformat(),
            },
            headers=headers,
            occurred_at=occurred_at,
            available_at=occurred_at,
            attempts=0,
        )
        self._session.add(row)

    async def add_audit(self, event: AuditEvent) -> None:
        """Добавить audit-событие."""
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
                "message_id": None,
                "channel": None,
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
