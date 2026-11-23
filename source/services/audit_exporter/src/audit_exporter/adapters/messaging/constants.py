"""Строковые константы обмена RabbitMQ."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

EVENTS_EXCHANGE: Final = "loan-debtors.events"
CONTENT_TYPE_JSON: Final = "application/json"
RETRY_TTL_MILLISECONDS: Final = 60_000
RETRY_EXCHANGE: Final = ""
RETRY_DELAY_HEADER: Final = "x-delay"
AUDIT_QUEUE_NAME: Final = "audit.events"
AUDIT_DLQ_ROUTING_KEY: Final = "audit.events.dlq"


class RoutingKey(StrEnum):
    """Имена событий и routing keys exchange."""

    CAMPAIGN_SCHEDULED = "campaign.scheduled"
    CAMPAIGN_CANCELLED = "campaign.cancelled"
    CAMPAIGN_START = "campaign.start"
    MESSAGE_SEND = "message.send"
    MESSAGE_SENT = "message.sent"
    MESSAGE_FAILED = "message.failed"
    AUDIT_EVENT = "audit.event"


class QueueName(StrEnum):
    """Имена основных очередей."""

    SCHEDULER_COMMANDS = "scheduler.commands"
    NOTIFICATION_COMMANDS = "notification.commands"
    EMAIL_COMMANDS = "email.commands"
    NOTIFICATION_RESULTS = "notification.results"
    AUDIT_EVENTS = "audit.events"


@dataclass(frozen=True, slots=True)
class QueueDefinition:
    """Описание очереди, retry-очереди и DLQ.

    Attributes:
        name: Имя основной очереди.
        routing_keys: Ключи, которые привязывают очередь к exchange.
    """

    name: QueueName
    routing_keys: tuple[RoutingKey, ...]

    @property
    def retry_name(self) -> str:
        """Вернуть имя retry-очереди."""
        return f"{self.name.value}.retry"

    @property
    def dlq_name(self) -> str:
        """Вернуть имя dead-letter очереди."""
        return f"{self.name.value}.dlq"


QUEUE_DEFINITIONS: Final[tuple[QueueDefinition, ...]] = (
    QueueDefinition(
        name=QueueName.SCHEDULER_COMMANDS,
        routing_keys=(RoutingKey.CAMPAIGN_SCHEDULED, RoutingKey.CAMPAIGN_CANCELLED),
    ),
    QueueDefinition(
        name=QueueName.NOTIFICATION_COMMANDS,
        routing_keys=(RoutingKey.CAMPAIGN_START,),
    ),
    QueueDefinition(
        name=QueueName.EMAIL_COMMANDS,
        routing_keys=(RoutingKey.MESSAGE_SEND,),
    ),
    QueueDefinition(
        name=QueueName.NOTIFICATION_RESULTS,
        routing_keys=(RoutingKey.MESSAGE_SENT, RoutingKey.MESSAGE_FAILED),
    ),
    QueueDefinition(
        name=QueueName.AUDIT_EVENTS,
        routing_keys=(RoutingKey.AUDIT_EVENT,),
    ),
)
