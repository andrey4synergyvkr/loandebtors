"""Запись команд message.send в outbox одной транзакцией с состоянием."""

from datetime import UTC, datetime
from uuid import uuid4

from opentelemetry import propagate
from sqlalchemy.ext.asyncio import AsyncSession

from notifications.adapters.messaging.constants import EVENTS_EXCHANGE, RoutingKey
from notifications.adapters.persistence.models import OutboxRow
from notifications.domain import NotificationCommand


class SqlAlchemyMessageCommandOutbox:
    """Добавляет команды message.send в outbox."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def add(
        self,
        command: NotificationCommand,
        correlation_id: str,
        trace_id: str | None,
        occurred_at: datetime | None = None,
        available_at: datetime | None = None,
    ) -> None:
        """Записать команду message.send, при необходимости отложенно."""
        moment = (occurred_at or datetime.now(UTC)).astimezone(UTC)
        ready_at = (available_at or moment).astimezone(UTC)
        headers: dict[str, str] = {"correlation_id": correlation_id}
        if trace_id is not None:
            headers["trace_id"] = trace_id
        propagate.inject(headers)
        self._session.add(
            OutboxRow(
                id=uuid4(),
                event_type=RoutingKey.MESSAGE_SEND.value,
                exchange=EVENTS_EXCHANGE,
                routing_key=RoutingKey.MESSAGE_SEND.value,
                payload={
                    "message_id": str(command.message_id),
                    "campaign_id": str(command.campaign_id),
                    "debtor_id": command.debtor_id,
                    "channel": command.channel,
                    "template_key": command.template_key,
                    "template_version": command.template_version,
                    "variables": dict(command.variables),
                    "recipient": {
                        "channel": command.recipient.channel,
                        "address": command.recipient.address,
                    },
                    "idempotency_key": command.idempotency_key,
                },
                headers=headers,
                occurred_at=moment,
                available_at=ready_at,
                attempts=0,
            )
        )
