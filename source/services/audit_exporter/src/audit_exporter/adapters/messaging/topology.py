"""Объявление топологии RabbitMQ."""

from typing import Any

from aio_pika import ExchangeType
from aio_pika.abc import AbstractChannel

from audit_exporter.adapters.messaging.constants import (
    EVENTS_EXCHANGE,
    QUEUE_DEFINITIONS,
    RETRY_EXCHANGE,
    RETRY_TTL_MILLISECONDS,
)


async def declare_topology(
    channel: AbstractChannel,
    retry_ttl_milliseconds: int = RETRY_TTL_MILLISECONDS,
) -> None:
    """Объявить exchange, основные очереди, retry-очереди и DLQ."""
    exchange = await channel.declare_exchange(
        EVENTS_EXCHANGE,
        ExchangeType.TOPIC,
        durable=True,
    )

    for definition in QUEUE_DEFINITIONS:
        retry_arguments: dict[str, Any] = {
            "x-message-ttl": retry_ttl_milliseconds,
            "x-dead-letter-exchange": RETRY_EXCHANGE,
            "x-dead-letter-routing-key": definition.name.value,
        }
        retry_queue = await channel.declare_queue(
            definition.retry_name,
            durable=True,
            arguments=retry_arguments,
        )
        await retry_queue.bind(exchange, routing_key=definition.retry_name)

        dlq = await channel.declare_queue(definition.dlq_name, durable=True)
        await dlq.bind(exchange, routing_key=definition.dlq_name)

        queue_arguments: dict[str, Any] = {
            "x-dead-letter-exchange": EVENTS_EXCHANGE,
            "x-dead-letter-routing-key": definition.retry_name,
        }
        queue = await channel.declare_queue(
            definition.name.value,
            durable=True,
            arguments=queue_arguments,
        )
        for routing_key in definition.routing_keys:
            await queue.bind(exchange, routing_key=routing_key.value)
