"""Фоновый публикатор записей outbox."""

import asyncio
import logging
import time
from datetime import datetime

from notifications.adapters.messaging.publisher import RabbitMQPublisher
from notifications.config import Settings
from notifications.infrastructure.metrics import EVENT_TYPE_ATTRIBUTE, Metrics
from notifications.ports.clock import Clock
from notifications.ports.outbox import OutboxEntry, OutboxStore

logger = logging.getLogger(__name__)

RELAY_TASK_NAME: str = "outbox-relay"
STOP_TIMEOUT_SECONDS: float = 10.0


class OutboxRelay:
    """Периодически публикует готовые записи outbox в RabbitMQ."""

    def __init__(
        self,
        store: OutboxStore,
        publisher: RabbitMQPublisher,
        settings: Settings,
        metrics: Metrics,
        clock: Clock,
    ) -> None:
        """Сохранить зависимости relay."""
        self._store = store
        self._publisher = publisher
        self._settings = settings
        self._metrics = metrics
        self._clock = clock
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_iteration_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error: str | None = None

    @property
    def last_iteration_at(self) -> datetime | None:
        """Вернуть время последней завершённой итерации."""
        return self._last_iteration_at

    @property
    def last_success_at(self) -> datetime | None:
        """Вернуть время последней успешной итерации."""
        return self._last_success_at

    @property
    def last_error(self) -> str | None:
        """Вернуть описание последней ошибки."""
        return self._last_error

    async def start(self) -> None:
        """Запустить фоновую задачу relay."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=RELAY_TASK_NAME)

    async def stop(self) -> None:
        """Остановить фоновую задачу и дождаться её завершения."""
        self._stop.set()
        task = self._task
        self._task = None
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=STOP_TIMEOUT_SECONDS)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        """Выполнять итерации relay до получения сигнала остановки."""
        while not self._stop.is_set():
            await self._run_once()
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._settings.outbox_poll_interval_seconds,
                )
            except TimeoutError:
                continue

    async def _run_once(self) -> None:
        """Выполнить одну итерацию публикации."""
        started_at = self._clock.now()
        started_monotonic = time.monotonic()
        try:
            await self._publisher.ensure_ready()
            result = await self._store.process_ready(
                self._settings.outbox_batch_size,
                started_at,
                self._publish,
            )
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._metrics.outbox_errors.add(1)
            logger.exception("Итерация outbox relay завершилась ошибкой")
        else:
            self._last_success_at = self._clock.now()
            self._last_error = None
            self._metrics.outbox_failures.add(result.failed)
            self._metrics.outbox_batch_size.record(result.published + result.failed)
        finally:
            self._last_iteration_at = self._clock.now()
            self._metrics.outbox_processing_duration.record(time.monotonic() - started_monotonic)

    async def _publish(self, entry: OutboxEntry) -> None:
        """Опубликовать одну запись outbox."""
        await self._publisher.publish(
            exchange=entry.exchange,
            routing_key=entry.routing_key,
            payload=entry.payload,
            headers=entry.headers,
        )
        self._metrics.outbox_published.add(1, {EVENT_TYPE_ATTRIBUTE: entry.event_type})
