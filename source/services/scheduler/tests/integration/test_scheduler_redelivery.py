"""Интеграционная проверка retry-очереди Scheduler."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from scheduler.adapters.messaging.commands import parse_command
from scheduler.adapters.messaging.connection import RabbitMQConnection
from scheduler.adapters.messaging.constants import EVENTS_EXCHANGE, QueueName, RoutingKey
from scheduler.adapters.messaging.publisher import RabbitMQPublisher
from scheduler.config import Settings
from scheduler.domain import CampaignScheduled

pytestmark = pytest.mark.integration

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


async def test_retry_returns_scheduled_with_queue_routing_key(
    connection: RabbitMQConnection,
) -> None:
    """После retry campaign.scheduled приходит с ключом очереди и разбирается."""
    publisher = RabbitMQPublisher(connection)
    campaign_id = uuid4()
    run_at = datetime.now(UTC) + timedelta(days=1)
    await publisher.publish(
        exchange=EVENTS_EXCHANGE,
        routing_key=RoutingKey.CAMPAIGN_SCHEDULED.value,
        payload={
            "campaign_id": str(campaign_id),
            "schedule": {
                "kind": "one_off",
                "timezone": "Europe/Moscow",
                "run_at": run_at.isoformat(),
                "cron": None,
            },
            "occurred_at": datetime.now(UTC).isoformat(),
        },
        headers={"correlation_id": "scheduler-retry-test"},
    )
    channel = await connection.open_consumer_channel(prefetch_count=1)
    queue = await channel.get_queue(QueueName.SCHEDULER_COMMANDS.value, ensure=True)
    first = await queue.get(fail=False, no_ack=False, timeout=5)
    assert first is not None
    assert first.routing_key == RoutingKey.CAMPAIGN_SCHEDULED.value
    await first.nack(requeue=False)

    await asyncio.sleep(2.0)

    retried = await queue.get(fail=False, no_ack=False, timeout=5)
    assert retried is not None
    assert retried.routing_key == QueueName.SCHEDULER_COMMANDS.value
    command = parse_command(retried.routing_key or "", retried.body)
    assert isinstance(command, CampaignScheduled)
    assert str(command.campaign_id) == str(campaign_id)
    await retried.ack()
