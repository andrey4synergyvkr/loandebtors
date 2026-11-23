"""Консьюмер очереди email.commands."""

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any, Final

from aio_pika.abc import AbstractChannel, AbstractIncomingMessage
from opentelemetry import propagate, trace
from pydantic import ValidationError as PydanticValidationError

from email_channel.adapters.messaging.connection import RabbitMQConnection
from email_channel.adapters.messaging.constants import EVENTS_EXCHANGE, QueueName
from email_channel.adapters.messaging.publisher import RabbitMQPublisher
from email_channel.adapters.messaging.schemas import NotificationCommandPayload, to_domain
from email_channel.adapters.messaging.serialization import decode_payload
from email_channel.application.config import RequestContext
from email_channel.application.delivery import (
    DeliveryStatus,
    EmailDeliveryService,
)
from email_channel.config import Settings
from email_channel.domain import ValidationError
from email_channel.infrastructure.correlation import (
    bind_correlation_id,
    new_correlation_id,
    reset_correlation_id,
)
from email_channel.infrastructure.metrics import (
    DELIVERY_OUTCOME_ATTRIBUTE,
    Metrics,
)
from email_channel.infrastructure.tracing import current_trace_id

logger = logging.getLogger(__name__)

TRACER_NAME: Final = "loandebtors.email_channel"
CONSUMER_TASK_NAME: Final = "email-commands-consumer"
STOP_TIMEOUT_SECONDS: float = 10.0
EMAIL_QUEUE_NAME: Final = QueueName.EMAIL_COMMANDS.value
EMAIL_DLQ_ROUTING_KEY: Final = f"{EMAIL_QUEUE_NAME}.dlq"
VALIDATION_REASON: Final = "validation"
TRANSIENT_REASON: Final = "transient"
RETRY_EXHAUSTED_REASON: Final = "retry_exhausted"
DLQ_ERROR_HEADER: Final = "x-error"
CORRELATION_ID_HEADER: Final = "correlation_id"
MAX_ERROR_LENGTH: Final = 500


class EmailCommandConsumer:
    """Потребляет message.send и отправляет письма с manual ack."""

    def __init__(
        self,
        connection: RabbitMQConnection,
        publisher: RabbitMQPublisher,
        delivery: EmailDeliveryService,
        settings: Settings,
        metrics: Metrics,
    ) -> None:
        """Сохранить зависимости консьюмера."""
        self._connection = connection
        self._publisher = publisher
        self._delivery = delivery
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
            self._metrics.consumer_running.set(0)
            return
        try:
            await asyncio.wait_for(task, timeout=STOP_TIMEOUT_SECONDS)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except Exception:
            logger.exception("Консьюмер email.commands завершился с ошибкой")
        finally:
            self._running = False
            self._metrics.consumer_running.set(0)

    async def handle(self, message: AbstractIncomingMessage) -> None:
        """Обработать одно сообщение message.send."""
        headers: dict[str, Any] = dict(message.headers or {})
        correlation_id = str(headers.get(CORRELATION_ID_HEADER) or new_correlation_id())
        token = bind_correlation_id(correlation_id)
        started_at = time.monotonic()
        try:
            parent_context = propagate.extract(headers)
            with self._tracer.start_as_current_span(
                "email.message.process",
                context=parent_context,
            ) as span:
                span.set_attribute("messaging.system", "rabbitmq")
                span.set_attribute("messaging.destination.name", EMAIL_QUEUE_NAME)
                span.set_attribute("messaging.operation", "process")
                try:
                    payload = decode_payload(message.body)
                    command = to_domain(NotificationCommandPayload.model_validate(payload))
                except (PydanticValidationError, ValidationError) as exc:
                    self._metrics.email_command_failures.add(
                        1,
                        {DELIVERY_OUTCOME_ATTRIBUTE: VALIDATION_REASON},
                    )
                    logger.warning(
                        "message.send отклонен и отправлен в DLQ",
                        extra={"event": "email_command_rejected", "reason": str(exc)},
                    )
                    await self._dead_letter(message, exc, headers, VALIDATION_REASON)
                    return

                span.set_attribute("messaging.message_id", str(command.message_id))
                span.set_attribute("audit.campaign_id", str(command.campaign_id))
                try:
                    result = await self._delivery.handle(
                        command,
                        RequestContext(correlation_id, current_trace_id()),
                    )
                except Exception as exc:
                    self._metrics.email_command_failures.add(
                        1,
                        {DELIVERY_OUTCOME_ATTRIBUTE: TRANSIENT_REASON},
                    )
                    logger.exception(
                        "Ошибка обработки message.send",
                        extra={
                            "event": "email_command_failed",
                            "message_id": str(command.message_id),
                            "campaign_id": str(command.campaign_id),
                        },
                    )
                    if self._retry_count(headers) >= self._settings.rabbitmq_retry_max_attempts:
                        try:
                            await self._delivery.record_consumer_failure(
                                command,
                                RequestContext(correlation_id, current_trace_id()),
                                "consumer_retry_exhausted",
                                str(exc),
                            )
                        except Exception:
                            logger.exception("Не удалось сохранить message.failed перед отправкой в DLQ")
                        await self._dead_letter(message, exc, headers, RETRY_EXHAUSTED_REASON)
                    else:
                        await message.nack(requeue=False)
                    return

                self._record_result(result.status)
                self._metrics.email_send_duration.record(
                    time.monotonic() - started_at,
                    {DELIVERY_OUTCOME_ATTRIBUTE: result.status.value},
                )
                await message.ack()
                logger.info(
                    "message.send обработан",
                    extra={
                        "event": "email_command_processed",
                        "message_id": str(command.message_id),
                        "campaign_id": str(command.campaign_id),
                        "outcome": result.status.value,
                    },
                )
        finally:
            reset_correlation_id(token)

    def _record_result(self, status: DeliveryStatus) -> None:
        """Увеличить счётчик по итоговому статусу."""
        if status is DeliveryStatus.SENT:
            self._metrics.email_sent.add(1)
        elif status is DeliveryStatus.FAILED:
            self._metrics.email_failed.add(1)
        else:
            self._metrics.email_duplicates.add(1)

    async def _run(self) -> None:
        """Подключаться к очереди и переподключаться после ошибок."""
        while not self._stop.is_set():
            try:
                await self._connection.start()
                channel = await self._connection.open_consumer_channel(
                    prefetch_count=self._settings.rabbitmq_prefetch_count,
                )
                queue = await channel.get_queue(EMAIL_QUEUE_NAME)
                consumer_tag = await queue.consume(self.handle, no_ack=False)
                self._running = True
                self._last_error = None
                self._metrics.consumer_running.set(1)
                logger.info("Консьюмер email.commands запущен")
                await self._wait_for_stop_or_close(channel)
                await queue.cancel(consumer_tag)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._metrics.consumer_reconnects.add(1)
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Консьюмер email.commands остановлен с ошибкой")
                await self._sleep_before_reconnect()
            finally:
                self._running = False
                self._metrics.consumer_running.set(0)

    async def _wait_for_stop_or_close(self, channel: AbstractChannel) -> None:
        """Ждать остановки сервиса или закрытия канала."""
        stop_task = asyncio.create_task(self._stop.wait())
        closed_task = asyncio.ensure_future(channel.closed())
        try:
            await asyncio.wait({stop_task, closed_task}, return_when=asyncio.FIRST_COMPLETED)
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
                timeout=self._settings.email_consumer_reconnect_seconds,
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
                EMAIL_DLQ_ROUTING_KEY,
                message.body,
                dlq_headers,
            )
        except Exception:
            logger.exception("Не удалось опубликовать message.send в DLQ")
            await message.nack(requeue=False)
            return
        await message.ack()
        self._metrics.email_command_failures.add(
            1,
            {DELIVERY_OUTCOME_ATTRIBUTE: reason},
        )

    @staticmethod
    def _retry_count(headers: Mapping[str, Any]) -> int:
        """Посчитать число dead-letter переходов из email.commands."""
        deaths = headers.get("x-death")
        if not isinstance(deaths, list):
            return 0
        total = 0
        for death in deaths:
            if isinstance(death, Mapping) and death.get("queue") == EMAIL_QUEUE_NAME:
                count = death.get("count", 0)
                if isinstance(count, int) and not isinstance(count, bool):
                    total += count
        return total
