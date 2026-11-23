"""Проверка сбора метрик очередей Audit Exporter."""

from typing import cast

from audit_exporter.adapters.messaging.connection import RabbitMQConnection
from audit_exporter.adapters.messaging.consumer import AuditEventConsumer
from audit_exporter.adapters.messaging.queue_metrics import QueueMetricsCollector
from audit_exporter.infrastructure.metrics import Metrics


class FakeGauge:
    """Gauge, который запоминает значения."""

    def __init__(self) -> None:
        """Создать пустой список значений."""
        self.values: list[tuple[int, dict[str, str] | None]] = []

    def set(self, value: int, attributes: dict[str, str] | None = None) -> None:
        """Запомнить значение."""
        self.values.append((value, attributes))


class FakeCounter:
    """Counter, который запоминает приращения."""

    def __init__(self) -> None:
        """Создать пустой список приращений."""
        self.values: list[int] = []

    def add(self, value: int, attributes: dict[str, str] | None = None) -> None:
        """Запомнить приращение."""
        self.values.append(value)


class FakeMetrics:
    """Набор метрик для проверки."""

    def __init__(self) -> None:
        """Создать gauges и counter."""
        self.queue_messages = FakeGauge()
        self.consumer_running = FakeGauge()
        self.consumer_reconnects = FakeCounter()


class FakeDeclarationResult:
    """Результат объявления очереди с числом сообщений."""

    def __init__(self, message_count: int) -> None:
        """Сохранить число сообщений."""
        self.message_count = message_count


class FakeQueue:
    """Очередь с заданным числом сообщений."""

    def __init__(self, message_count: int) -> None:
        """Сохранить результат объявления."""
        self.declaration_result = FakeDeclarationResult(message_count)


class FakeChannel:
    """Канал, который отдаёт очереди с заданной глубиной."""

    def __init__(self, counts: dict[str, int]) -> None:
        """Сохранить глубину по именам очередей."""
        self._counts = counts

    async def get_queue(self, name: str) -> FakeQueue:
        """Вернуть очередь по имени."""
        return FakeQueue(self._counts[name])


class FakeConnection:
    """Подключение, которое отдаёт канал."""

    def __init__(self, counts: dict[str, int] | None = None, error: Exception | None = None) -> None:
        """Сохранить глубину и возможную ошибку."""
        self._counts = counts or {}
        self._error = error

    async def channel(self) -> FakeChannel:
        """Вернуть канал или выбросить ошибку."""
        if self._error is not None:
            raise self._error
        return FakeChannel(self._counts)


class FakeConsumer:
    """Консьюмер с заданным состоянием."""

    def __init__(self, is_running: bool) -> None:
        """Сохранить состояние."""
        self.is_running = is_running


def _collector(
    connection: FakeConnection,
    consumer: FakeConsumer,
    metrics: FakeMetrics,
) -> QueueMetricsCollector:
    return QueueMetricsCollector(
        connection=cast(RabbitMQConnection, connection),
        consumer=cast(AuditEventConsumer, consumer),
        metrics=cast(Metrics, metrics),
        interval_seconds=10.0,
    )


async def test_collect_once_records_queue_depth_and_consumer_state() -> None:
    """Сбор пишет глубину трёх очередей и признак запуска консьюмера."""
    metrics = FakeMetrics()
    connection = FakeConnection(
        {
            "audit.events": 5,
            "audit.events.retry": 2,
            "audit.events.dlq": 1,
        }
    )
    collector = _collector(connection, FakeConsumer(True), metrics)

    await collector.collect_once()

    assert metrics.consumer_running.values == [(1, None)]
    values = {attributes["queue"]: value for value, attributes in metrics.queue_messages.values if attributes}
    assert values == {
        "audit.events": 5,
        "audit.events.retry": 2,
        "audit.events.dlq": 1,
    }


async def test_collect_once_marks_consumer_stopped_on_error() -> None:
    """Ошибка сбора не пробрасывается и сбрасывает признак консьюмера."""
    metrics = FakeMetrics()
    collector = _collector(
        FakeConnection(error=RuntimeError("rabbitmq is down")),
        FakeConsumer(True),
        metrics,
    )

    await collector.collect_once()

    assert metrics.consumer_running.values == [(0, None)]
    assert metrics.queue_messages.values == []
