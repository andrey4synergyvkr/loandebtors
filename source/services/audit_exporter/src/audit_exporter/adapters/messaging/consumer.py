"""Консьюмер очереди audit.events с retry и DLQ."""

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any, Final, Protocol

from aio_pika.abc import AbstractChannel, AbstractIncomingMessage
from opentelemetry import propagate, trace
from pydantic import ValidationError as PydanticValidationError

from audit_exporter.adapters.messaging.connection import RabbitMQConnection
from audit_exporter.adapters.messaging.constants import (
    AUDIT_DLQ_ROUTING_KEY,
    AUDIT_QUEUE_NAME,
    EVENTS_EXCHANGE,
)
from audit_exporter.adapters.messaging.schemas import AuditEventPayload, to_domain
from audit_exporter.adapters.messaging.serialization import decode_payload
from audit_exporter.application.audit_ingest import AuditIngestService
from audit_exporter.config import Settings
from audit_exporter.domain import ConflictError, ValidationError
from audit_exporter.infrastructure.correlation import (
    bind_correlation_id,
    new_correlation_id,
    reset_correlation_id,
)
from audit_exporter.infrastructure.metrics import (
    AUDIT_ACTION_ATTRIBUTE,
    AUDIT_REASON_ATTRIBUTE,
    AUDIT_SOURCE_ATTRIBUTE,
    Metrics,
)

logger = logging.getLogger(__name__)

TRACER_NAME: Final = "loandebtors.audit_exporter"
CONSUMER_TASK_NAME: Final = "audit-events-consumer"
STOP_TIMEOUT_SECONDS: float = 10.0
VALIDATION_REASON: Final = "validation"
CONFLICT_REASON: Final = "conflict"
RETRY_EXHAUSTED_REASON: Final = "retry_exhausted"
TRANSIENT_REASON: Final = "transient"
DLQ_ERROR_HEADER: Final = "x-error"
CORRELATION_ID_HEADER: Final = "correlation_id"
MAX_ERROR_LENGTH: Final = 500


class RawPublisher(Protocol):
    """Публикатор исходного тела сообщения."""

    async def publish_raw(
        self,
        exchange: str,
        routing_key: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> None:
        """Опубликовать исходное тело."""
        ...


class AuditEventConsumer:
    """Потребляет audit.event и пишет журнал с manual ack."""

    def __init__(
        self,
        connection: RabbitMQConnection,
        publisher: RawPublisher,
        ingest: AuditIngestService,
        settings: Settings,
        metrics: Metrics,
    ) -> None:
        """Сохранить зависимости консьюмера."""
        self._connection = connection
        self._publisher = publisher
        self._ingest = ingest
        self._settings = settings
        self._metrics = metrics
        self._tracer = trace.get_tracer(TRACER_NAME)
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._last_error: str | None = None

    @property
    def is_running(self) -> bool:
        """Вернуть True, если консьюмер подключён к очереди."""
        return self._running

    @property
    def last_error(self) -> str | None:
        """Вернуть описание последней ошибки supervisor."""
        return self._last_error

    async def start(self) -> None:
        """Запустить фоновую задачу консьюмера."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=CONSUMER_TASK_NAME)

    async def stop(self) -> None:
        """Остановить консьюмер и дождаться завершения задачи."""
        self._stop.set()
        task, self._task = self._task, None
        if task is None:
            self._running = False
            return
        try:
            await asyncio.wait_for(task, timeout=STOP_TIMEOUT_SECONDS)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except Exception:
            logger.exception("Консьюмер audit.events завершился с ошибкой")
        finally:
            self._running = False

    async def handle(self, message: AbstractIncomingMessage) -> None:
        """Обработать одно сообщение audit.event."""
        headers: dict[str, Any] = dict(message.headers or {})
        correlation_id = str(headers.get(CORRELATION_ID_HEADER) or new_correlation_id())
        token = bind_correlation_id(correlation_id)
        started_at = time.monotonic()
        try:
            parent_context = propagate.extract(headers)
            with self._tracer.start_as_current_span(
                "audit.event.process",
                context=parent_context,
            ) as span:
                span.set_attribute("messaging.system", "rabbitmq")
                span.set_attribute("messaging.destination.name", AUDIT_QUEUE_NAME)
                span.set_attribute("messaging.operation", "process")
                try:
                    payload = decode_payload(message.body)
                    event = to_domain(AuditEventPayload.model_validate(payload))
                except (PydanticValidationError, ValidationError) as exc:
                    span.set_attribute("audit.rejected", "true")
                    self._metrics.audit_ingest_failures.add(
                        1,
                        {AUDIT_REASON_ATTRIBUTE: VALIDATION_REASON},
                    )
                    logger.warning(
                        "audit.event отклонен и отправлен в DLQ",
                        extra={
                            "event": "audit_event_rejected",
                            "reason": str(exc),
                        },
                    )
                    await self._dead_letter(message, exc, headers, VALIDATION_REASON)
                    return

                span.set_attribute("audit.event_id", str(event.event_id))
                span.set_attribute("audit.action", event.action.value)
                span.set_attribute("audit.source_service", event.service)
                try:
                    await self._ingest.handle(event)
                except ConflictError as exc:
                    span.set_attribute("audit.conflict", "true")
                    self._metrics.audit_conflicts.add(1)
                    logger.error(
                        "Конфликт audit.event: событие с таким event_id уже записано",
                        extra={
                            "event": "audit_event_conflict",
                            "event_id": str(event.event_id),
                            "action": event.action.value,
                            "source_service": event.service,
                            "reason": str(exc),
                        },
                    )
                    await self._dead_letter(message, exc, headers, CONFLICT_REASON)
                    return
                except Exception as exc:
                    self._metrics.audit_ingest_failures.add(
                        1,
                        {AUDIT_REASON_ATTRIBUTE: TRANSIENT_REASON},
                    )
                    logger.exception(
                        "Ошибка обработки audit.event",
                        extra={
                            "event": "audit_event_failed",
                            "event_id": str(event.event_id),
                            "action": event.action.value,
                            "source_service": event.service,
                        },
                    )
                    if self._retry_count(headers) >= self._settings.rabbitmq_retry_max_attempts:
                        await self._dead_letter(message, exc, headers, RETRY_EXHAUSTED_REASON)
                    else:
                        await message.nack(requeue=False)
                    return

                await message.ack()
                self._metrics.audit_ingested.add(
                    1,
                    {
                        AUDIT_ACTION_ATTRIBUTE: event.action.value,
                        AUDIT_SOURCE_ATTRIBUTE: event.service,
                    },
                )
                self._metrics.audit_ingest_duration.record(
                    time.monotonic() - started_at,
                    {AUDIT_ACTION_ATTRIBUTE: event.action.value},
                )
                logger.info(
                    "audit.event записан в журнал",
                    extra={
                        "event": "audit_event_ingested",
                        "event_id": str(event.event_id),
                        "action": event.action.value,
                        "source_service": event.service,
                    },
                )
        finally:
            reset_correlation_id(token)

    async def _run(self) -> None:
        """Подключаться к очереди и переподключаться после ошибок."""
        while not self._stop.is_set():
            try:
                await self._connection.start()
                channel = await self._connection.channel()
                queue = await channel.get_queue(AUDIT_QUEUE_NAME)
                consumer_tag = await queue.consume(self.handle, no_ack=False)
                self._running = True
                self._last_error = None
                logger.info("Консьюмер audit.events запущен")
                await self._wait_for_stop_or_close(channel)
                await queue.cancel(consumer_tag)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._metrics.consumer_reconnects.add(1)
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Консьюмер audit.events остановлен с ошибкой")
                await self._sleep_before_reconnect()
            finally:
                self._running = False

    async def _wait_for_stop_or_close(self, channel: AbstractChannel) -> None:
        """Ждать остановки сервиса или закрытия канала."""
        stop_task = asyncio.create_task(self._stop.wait())
        closed_task = asyncio.ensure_future(channel.closed())
        try:
            await asyncio.wait(
                {stop_task, closed_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (stop_task, closed_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stop_task, closed_task, return_exceptions=True)

    async def _sleep_before_reconnect(self) -> None:
        """Подождать перед повторным подключением или завершиться при остановке."""
        try:
            await asyncio.wait_for(
                self._stop.wait(),
                timeout=self._settings.audit_consumer_reconnect_seconds,
            )
        except TimeoutError:
            return

    async def _dead_letter(
        self,
        message: AbstractIncomingMessage,
        error: Exception,
        headers: Mapping[str, Any],
        reason: str,
    ) -> None:
        """Опубликовать сообщение в DLQ и подтвердить исходное сообщение."""
        dlq_headers: dict[str, str] = {
            str(key): str(value) for key, value in headers.items() if isinstance(value, str | int | float)
        }
        dlq_headers[DLQ_ERROR_HEADER] = f"{type(error).__name__}: {error}"[:MAX_ERROR_LENGTH]
        try:
            await self._publisher.publish_raw(
                EVENTS_EXCHANGE,
                AUDIT_DLQ_ROUTING_KEY,
                message.body,
                dlq_headers,
            )
        except Exception:
            logger.exception("Не удалось опубликовать audit.event в DLQ")
            await message.nack(requeue=False)
            return
        await message.ack()
        self._metrics.audit_dlq_published.add(1, {AUDIT_REASON_ATTRIBUTE: reason})

    @staticmethod
    def _retry_count(headers: Mapping[str, Any]) -> int:
        """Посчитать число dead-letter переходов сообщения из audit.events."""
        deaths = headers.get("x-death")
        if not isinstance(deaths, list):
            return 0
        total = 0
        for death in deaths:
            if isinstance(death, Mapping) and death.get("queue") == AUDIT_QUEUE_NAME:
                count = death.get("count", 0)
                if isinstance(count, int) and not isinstance(count, bool):
                    total += count
        return total
