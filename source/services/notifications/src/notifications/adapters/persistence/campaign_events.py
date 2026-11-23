"""Запись событий кампании в outbox одной транзакцией с состоянием."""

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

from opentelemetry import propagate
from sqlalchemy.ext.asyncio import AsyncSession

from notifications.adapters.messaging.constants import EVENTS_EXCHANGE, RoutingKey
from notifications.adapters.persistence.campaign_json import schedule_to_json
from notifications.adapters.persistence.models import OutboxRow
from notifications.domain import CampaignCancelled, CampaignScheduled, CampaignStart


class SqlAlchemyCampaignEventOutbox:
    """Добавляет campaign.scheduled и campaign.cancelled в outbox."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def add_scheduled(
        self,
        event: CampaignScheduled,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Записать campaign.scheduled в outbox."""
        occurred_at = event.occurred_at.astimezone(UTC)
        payload = {
            "campaign_id": str(event.campaign_id),
            "schedule": schedule_to_json(event.schedule),
            "occurred_at": occurred_at.isoformat(),
        }
        self._add(RoutingKey.CAMPAIGN_SCHEDULED, payload, occurred_at, correlation_id, trace_id)

    async def add_cancelled(
        self,
        event: CampaignCancelled,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Записать campaign.cancelled в outbox."""
        occurred_at = event.occurred_at.astimezone(UTC)
        payload = {
            "campaign_id": str(event.campaign_id),
            "occurred_at": occurred_at.isoformat(),
        }
        self._add(RoutingKey.CAMPAIGN_CANCELLED, payload, occurred_at, correlation_id, trace_id)

    async def add_start(
        self,
        event: CampaignStart,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Записать campaign.start в outbox."""
        occurred_at = event.occurred_at.astimezone(UTC)
        payload = {
            "campaign_id": str(event.campaign_id),
            "scheduled_for": event.scheduled_for.astimezone(UTC).isoformat(),
            "occurred_at": occurred_at.isoformat(),
        }
        self._add(RoutingKey.CAMPAIGN_START, payload, occurred_at, correlation_id, trace_id)

    def _add(
        self,
        routing_key: RoutingKey,
        payload: Mapping[str, object],
        occurred_at: datetime,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Добавить запись outbox с routing key события."""
        headers: dict[str, str] = {"correlation_id": correlation_id}
        if trace_id is not None:
            headers["trace_id"] = trace_id
        propagate.inject(headers)
        self._session.add(
            OutboxRow(
                id=uuid4(),
                event_type=routing_key.value,
                exchange=EVENTS_EXCHANGE,
                routing_key=routing_key.value,
                payload=payload,
                headers=headers,
                occurred_at=occurred_at,
                available_at=occurred_at,
                attempts=0,
            )
        )
