"""Интеграционная проверка retry-очереди Notifications."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from notifications.adapters.messaging.commands import parse_result_command, parse_start_command
from notifications.adapters.messaging.connection import RabbitMQConnection
from notifications.adapters.messaging.constants import EVENTS_EXCHANGE, QueueName, RoutingKey
from notifications.adapters.messaging.publisher import RabbitMQPublisher
from notifications.config import Settings

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[5]
_RABBITMQ_IMAGE = "rabbitmq:3.13-alpine"
_RABBITMQ_LOG_TIMEOUT_SECONDS = 60


@pytest.fixture(scope="module")
def rabbitmq_url() -> Iterator[str]:
    """Поднять RabbitMQ или пропустить тест."""
    rabbitmq: DockerContainer | None = None
    try:
        rabbitmq = (
            DockerContainer(_RABBITMQ_IMAGE)
            .with_env("RABBITMQ_DEFAULT_USER", "loandebtors")
            .with_env("RABBITMQ_DEFAULT_PASS", "loandebtors")
            .with_exposed_ports(5672)
        )
        rabbitmq.waiting_for(
            LogMessageWaitStrategy("Server startup complete").with_startup_timeout(
                _RABBITMQ_LOG_TIMEOUT_SECONDS
            )
        ).start()
    except Exception as exc:
        if rabbitmq is not None:
            with suppress(Exception):
                rabbitmq.stop()
        pytest.skip(f"Docker или RabbitMQ недоступны: {exc}")

    assert rabbitmq is not None
    url = (
        "amqp://loandebtors:loandebtors@"
        f"{rabbitmq.get_container_host_ip()}:{rabbitmq.get_exposed_port(5672)}/"
    )
    try:
        yield url
    finally:
        with suppress(Exception):
            rabbitmq.stop()


@pytest.fixture
async def connection(rabbitmq_url: str) -> AsyncIterator[RabbitMQConnection]:
    """Открыть подключение с топологией и TTL retry 1 секунда."""
    settings = Settings(
        rabbitmq_url=rabbitmq_url,
        rabbitmq_retry_ttl_seconds=1.0,
    )
    connection = RabbitMQConnection(settings)
    await connection.start()
    try:
        yield connection
    finally:
        await connection.close()


async def test_retry_returns_message_with_queue_routing_key(
    connection: RabbitMQConnection,
) -> None:
    """После retry сообщение приходит с routing key очереди и разбирается."""
    publisher = RabbitMQPublisher(connection)
    campaign_id = uuid4()
    payload = {
        "campaign_id": str(campaign_id),
        "scheduled_for": "2026-12-01T10:00:00+00:00",
        "occurred_at": "2026-11-22T12:00:00+00:00",
    }
    await publisher.publish(
        exchange=EVENTS_EXCHANGE,
        routing_key=RoutingKey.CAMPAIGN_START.value,
        payload=payload,
        headers={"correlation_id": "retry-test"},
    )
    channel = await connection.open_consumer_channel(prefetch_count=1)
    queue = await channel.get_queue(QueueName.NOTIFICATION_COMMANDS.value, ensure=True)
    first = await queue.get(fail=False, no_ack=False, timeout=5)
    assert first is not None
    assert first.routing_key == RoutingKey.CAMPAIGN_START.value
    await first.nack(requeue=False)

    await asyncio.sleep(2.0)

    retried = await queue.get(fail=False, no_ack=False, timeout=5)
    assert retried is not None
    assert retried.routing_key == QueueName.NOTIFICATION_COMMANDS.value
    command = parse_start_command(retried.routing_key or "", retried.body)
    assert str(command.campaign_id) == str(campaign_id)
    await retried.ack()


async def test_result_retry_is_parsed_by_body(
    connection: RabbitMQConnection,
) -> None:
    """После retry результат приходит с ключом очереди и разбирается по телу."""
    publisher = RabbitMQPublisher(connection)
    message_id = uuid4()
    campaign_id = uuid4()
    await publisher.publish(
        exchange=EVENTS_EXCHANGE,
        routing_key=RoutingKey.MESSAGE_SENT.value,
        payload={
            "message_id": str(message_id),
            "campaign_id": str(campaign_id),
            "channel": "email",
            "attempt_number": 1,
            "provider_message_id": "smtp-1",
            "occurred_at": "2026-11-22T12:00:00+00:00",
        },
        headers={"correlation_id": "result-retry-test"},
    )
    channel = await connection.open_consumer_channel(prefetch_count=1)
    queue = await channel.get_queue(QueueName.NOTIFICATION_RESULTS.value, ensure=True)
    first = await queue.get(fail=False, no_ack=False, timeout=5)
    assert first is not None
    assert first.routing_key == RoutingKey.MESSAGE_SENT.value
    await first.nack(requeue=False)

    await asyncio.sleep(2.0)

    retried = await queue.get(fail=False, no_ack=False, timeout=5)
    assert retried is not None
    assert retried.routing_key == QueueName.NOTIFICATION_RESULTS.value
    command = parse_result_command(retried.routing_key or "", retried.body)
    assert str(command.message_id) == str(message_id)
    await retried.ack()
