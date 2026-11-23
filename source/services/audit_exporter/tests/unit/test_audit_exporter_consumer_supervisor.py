"""Проверка переподключения supervisor Audit Exporter."""

import asyncio
from typing import cast

from audit_exporter.adapters.messaging.connection import RabbitMQConnection
from audit_exporter.adapters.messaging.consumer import AuditEventConsumer
from audit_exporter.adapters.messaging.publisher import RabbitMQPublisher
from audit_exporter.application.audit_ingest import AuditIngestService
from audit_exporter.config import Settings
from audit_exporter.infrastructure.metrics import Metrics


class FakeCounter:
    """Counter, который запоминает приращения."""

    def __init__(self) -> None:
        """Создать пустой список."""
        self.values: list[int] = []

    def add(self, value: int, attributes: dict[str, str] | None = None) -> None:
        """Запомнить приращение."""
        self.values.append(value)


class FakeMetrics:
    """Метрики, нужные supervisor."""

    def __init__(self) -> None:
        """Создать счётчик переподключений."""
        self.consumer_reconnects = FakeCounter()


class FakeQueue:
    """Очередь, которая принимает consumer tag."""

    def __init__(self) -> None:
        """Создать флаг отмены."""
        self.cancelled = False

    async def consume(self, callback: object, no_ack: bool = False) -> str:
        """Вернуть тег консьюмера."""
        return "tag-1"

    async def cancel(self, consumer_tag: str) -> None:
        """Зафиксировать отмену."""
        self.cancelled = True


class FakeChannel:
    """Канал с очередью и незавершающимся closed."""

    def __init__(self) -> None:
        """Создать очередь."""
        self.queue = FakeQueue()

    async def get_queue(self, name: str) -> FakeQueue:
        """Вернуть очередь."""
        return self.queue

    def closed(self) -> asyncio.Future[bool]:
        """Вернуть future, который не завершается до отмены."""
        return asyncio.get_running_loop().create_future()


class FakeConnection:
    """Подключение, которое падает при первом старте."""

    def __init__(self) -> None:
        """Создать счётчик попыток."""
        self.starts = 0

    async def start(self) -> None:
        """Первый старт завершить ошибкой, второй успешно."""
        self.starts += 1
        if self.starts == 1:
            raise ConnectionError("rabbitmq is down")

    async def channel(self) -> FakeChannel:
        """Вернуть канал."""
        return FakeChannel()


def _settings() -> Settings:
    return Settings(
        service_name="audit_exporter",
        otel_enabled=False,
        check_dependencies=False,
        run_background_workers=False,
        audit_consumer_reconnect_seconds=0.01,
    )


async def test_consumer_reconnects_after_start_failure() -> None:
    """Supervisor повторяет подключение и фиксирует переподключение."""
    connection = FakeConnection()
    metrics = FakeMetrics()
    consumer = AuditEventConsumer(
        connection=cast(RabbitMQConnection, connection),
        publisher=cast(RabbitMQPublisher, object()),
        ingest=cast(AuditIngestService, object()),
        settings=_settings(),
        metrics=cast(Metrics, metrics),
    )

    await consumer.start()
    for _ in range(100):
        if consumer.is_running:
            break
        await asyncio.sleep(0.01)

    assert consumer.is_running is True
    assert connection.starts == 2
    assert metrics.consumer_reconnects.values == [1]

    await consumer.stop()
    assert consumer.is_running is False
