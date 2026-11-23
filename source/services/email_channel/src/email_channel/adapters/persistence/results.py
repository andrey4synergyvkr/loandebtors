"""Запись результатов доставки в outbox."""

from datetime import UTC
from uuid import uuid4

from opentelemetry import propagate
from sqlalchemy.ext.asyncio import AsyncSession

from email_channel.adapters.messaging.constants import EVENTS_EXCHANGE, RoutingKey
from email_channel.adapters.persistence.models import OutboxRow
from email_channel.domain import MessageFailed, MessageSent


class SqlAlchemyMessageResultOutbox:
    """Добавляет message.sent и message.failed в outbox текущей сессии."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def add_sent(
        self,
        event: MessageSent,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Добавить результат успешной отправки."""
        occurred_at = event.occurred_at.astimezone(UTC)
        headers = _headers(correlation_id, trace_id)
        self._session.add(
            OutboxRow(
                id=uuid4(),
                event_type=RoutingKey.MESSAGE_SENT.value,
                exchange=EVENTS_EXCHANGE,
                routing_key=RoutingKey.MESSAGE_SENT.value,
                payload={
                    "message_id": str(event.message_id),
                    "campaign_id": str(event.campaign_id),
                    "channel": event.channel,
                    "attempt_number": event.attempt_number,
                    "provider_message_id": event.provider_message_id,
                    "occurred_at": occurred_at.isoformat(),
                },
                headers=headers,
                occurred_at=occurred_at,
                available_at=occurred_at,
                attempts=0,
            )
        )

    async def add_failed(
        self,
        event: MessageFailed,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Добавить результат неудачной отправки."""
        occurred_at = event.occurred_at.astimezone(UTC)
        headers = _headers(correlation_id, trace_id)
        self._session.add(
            OutboxRow(
                id=uuid4(),
                event_type=RoutingKey.MESSAGE_FAILED.value,
                exchange=EVENTS_EXCHANGE,
                routing_key=RoutingKey.MESSAGE_FAILED.value,
                payload={
                    "message_id": str(event.message_id),
                    "campaign_id": str(event.campaign_id),
                    "channel": event.channel,
                    "attempt_number": event.attempt_number,
                    "outcome": event.outcome.value,
                    "retryable": event.retryable,
                    "error_code": event.error_code,
                    "error_message": event.error_message,
                    "occurred_at": occurred_at.isoformat(),
                },
                headers=headers,
                occurred_at=occurred_at,
                available_at=occurred_at,
                attempts=0,
            )
        )


def _headers(correlation_id: str, trace_id: str | None) -> dict[str, str]:
    """Собрать заголовки результата с trace context."""
    headers: dict[str, str] = {"correlation_id": correlation_id}
    if trace_id is not None:
        headers["trace_id"] = trace_id
    propagate.inject(headers)
    return headers
