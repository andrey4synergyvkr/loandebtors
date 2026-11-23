"""Сбор глубины очередей Audit Exporter и состояния консьюмера."""

import asyncio
import logging
from typing import Final

from audit_exporter.adapters.messaging.connection import RabbitMQConnection
from audit_exporter.adapters.messaging.constants import QUEUE_DEFINITIONS, QueueName
from audit_exporter.adapters.messaging.consumer import AuditEventConsumer
from audit_exporter.infrastructure.metrics import QUEUE_ATTRIBUTE, Metrics

logger = logging.getLogger(__name__)

COLLECTOR_TASK_NAME: Final = "audit-queue-metrics"
STOP_TIMEOUT_SECONDS: float = 10.0


def _audit_queue_names() -> tuple[str, ...]:
    """Вернуть основную, retry и DLQ очереди audit.events."""
    definition = next(item for item in QUEUE_DEFINITIONS if item.name is QueueName.AUDIT_EVENTS)
    return (definition.name.value, definition.retry_name, definition.dlq_name)


class QueueMetricsCollector:
    """Периодически публикует gauges глубины очередей и состояния консьюмера."""

    def __init__(
        self,
        connection: RabbitMQConnection,
        consumer: AuditEventConsumer,
        metrics: Metrics,
        interval_seconds: float,
    ) -> None:
        """Сохранить зависимости и интервал сбора."""
        self._connection = connection
        self._consumer = consumer
        self._metrics = metrics
        self._interval_seconds = interval_seconds
        self._queue_names = _audit_queue_names()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Запустить фоновую задачу сбора метрик."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=COLLECTOR_TASK_NAME)

    async def stop(self) -> None:
        """Остановить фоновую задачу."""
        self._stop.set()
        task, self._task = self._task, None
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=STOP_TIMEOUT_SECONDS)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def collect_once(self) -> None:
        """Один раз собрать глубину очередей и состояние консьюмера."""
        try:
            channel = await self._connection.channel()
            for queue_name in self._queue_names:
                queue = await channel.get_queue(queue_name)
                count = queue.declaration_result.message_count or 0
                self._metrics.queue_messages.set(count, {QUEUE_ATTRIBUTE: queue_name})
            self._metrics.consumer_running.set(1 if self._consumer.is_running else 0)
        except Exception:
            self._metrics.consumer_running.set(0)
            logger.warning("Не удалось собрать метрики очередей audit.events", exc_info=True)

    async def _run(self) -> None:
        """Выполнять сбор до сигнала остановки."""
        while not self._stop.is_set():
            await self.collect_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                continue
