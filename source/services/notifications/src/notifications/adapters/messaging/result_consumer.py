"""Потребитель результатов очереди notification.results."""

import asyncio
import logging
import time
from collections.abc import Mapping
from contextlib import suppress
from typing import Any, Final

from aio_pika.abc import AbstractChannel, AbstractIncomingMessage, AbstractQueue
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind

from notifications.adapters.messaging.commands import (
    decode_for_dead_letter,
    parse_result_command,
    retry_attempts,
    should_dead_letter,
)
from notifications.adapters.messaging.connection import RabbitMQConnection
from notifications.adapters.messaging.constants import EVENTS_EXCHANGE, QueueName
from notifications.adapters.messaging.publisher import RabbitMQPublisher
from notifications.application.common import RequestContext
from notifications.application.message_results import MessageResultService
from notifications.config import Settings
from notifications.domain import MessageFailed, MessageSent, ValidationError
from notifications.infrastructure.correlation import (
    bind_correlation_id,
    new_correlation_id,
    reset_correlation_id,
)
from notifications.infrastructure.metrics import EVENT_TYPE_ATTRIBUTE, Metrics

logger = logging.getLogger(__name__)

TRACER_NAME: str = "loandebtors.notifications"
CONSUMER_SPAN_NAME: str = "notifications.message_result"
CONSUMER_TASK_NAME: str = "notifications-result-consumer"
CONSUMER_RESTART_INTERVAL_SECONDS: float = 5.0
STOP_TIMEOUT_SECONDS: Final = 10.0
ROUTING_KEY_ATTRIBUTE: str = "messaging.routing_key"
ERROR_TYPE_HEADER: str = "x-error-type"
ERROR_MESSAGE_HEADER: str = "x-error-message"
ORIGINAL_ROUTING_KEY_HEADER: str = "x-original-routing-key"
ATTEMPTS_HEADER: str = "x-attempts"


class NotificationResultConsumer:
    """Принимает message.sent и message.failed с manual ack, retry и DLQ."""

    def __init__(
        self,
        connection: RabbitMQConnection,
        publisher: RabbitMQPublisher,
        service: MessageResultService,
        settings: Settings,
        metrics: Metrics,
    ) -> None:
        """Сохранить зависимости потребителя."""
        self._connection = connection
        self._publisher = publisher
        self._service = service
        self._settings = settings
        self._metrics = metrics
        self._tracer = trace.get_tracer(TRACER_NAME)
        self._channel: AbstractChannel | None = None
        self._queue: AbstractQueue | None = None
        self._consumer_tag: str | None = None
        self._last_error: str | None = None
        self._stop = asyncio.Event()
        self._active_handlers = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        """Вернуть признак активного потребителя."""
        return self._consumer_tag is not None and self._channel is not None and not self._channel.is_closed

    @property
    def last_error(self) -> str | None:
        """Вернуть описание последней ошибки обработки."""
        return self._last_error

    async def start(self) -> None:
        """Подписаться на очередь и запустить восстановление подписки."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        try:
            await self._subscribe()
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Не удалось подписаться на notification.results", exc_info=True)
        self._task = asyncio.create_task(self._supervise(), name=CONSUMER_TASK_NAME)

    async def stop(self) -> None:
        """Остановить восстановление подписки и закрыть канал."""
        self._stop.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._cancel_subscription()
        try:
            await asyncio.wait_for(self._idle.wait(), timeout=STOP_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning("Не все обработчики завершились до остановки потребителя")
        await self._close_channel()

    async def _cancel_subscription(self) -> None:
        """Отменить подписку, чтобы новые сообщения не поступали."""
        queue, tag = self._queue, self._consumer_tag
        self._consumer_tag = None
        if queue is not None and tag is not None:
            with suppress(Exception):
                await queue.cancel(tag)

    async def _subscribe(self) -> None:
        """Открыть канал и подписаться на очередь."""
        await self._close_channel()
        channel = await self._connection.open_consumer_channel(
            prefetch_count=self._settings.rabbitmq_prefetch_count,
        )
        try:
            queue = await channel.get_queue(QueueName.NOTIFICATION_RESULTS.value, ensure=True)
            consumer_tag = await queue.consume(self._handle, no_ack=False)
        except Exception:
            if not channel.is_closed:
                with suppress(Exception):
                    await channel.close()
            raise
        self._channel = channel
        self._queue = queue
        self._consumer_tag = consumer_tag
        self._last_error = None

    async def _supervise(self) -> None:
        """Переподписываться на очередь после потери соединения."""
        while not self._stop.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=CONSUMER_RESTART_INTERVAL_SECONDS,
                )
            if self._stop.is_set():
                return
            if self.is_running:
                continue
            try:
                await self._subscribe()
                logger.info("Подписка на notification.results восстановлена")
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Повторная подписка на notification.results не удалась",
                    exc_info=True,
                )

    async def _close_channel(self) -> None:
        """Закрыть текущий канал потребителя."""
        channel, self._channel = self._channel, None
        self._queue = None
        self._consumer_tag = None
        if channel is not None and not channel.is_closed:
            with suppress(Exception):
                await channel.close()

    async def _handle(self, message: AbstractIncomingMessage) -> None:
        """Обработать одно сообщение и подтвердить или отклонить его."""
        headers: dict[str, Any] = dict(message.headers or {})
        routing_key = message.routing_key or ""
        correlation_id = str(headers.get("correlation_id") or new_correlation_id())
        token = bind_correlation_id(correlation_id)
        started_at = time.monotonic()
        self._active_handlers += 1
        self._idle.clear()
        self._metrics.consumer_messages.add(1, {EVENT_TYPE_ATTRIBUTE: routing_key})
        try:
            trace_context = propagate.extract({str(key): str(value) for key, value in headers.items()})
            with self._tracer.start_as_current_span(
                CONSUMER_SPAN_NAME,
                context=trace_context,
                kind=SpanKind.CONSUMER,
            ) as span:
                span.set_attribute(ROUTING_KEY_ATTRIBUTE, routing_key)
                command = parse_result_command(routing_key, message.body)
                await self._dispatch(command, correlation_id)
        except ValidationError as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            published = await self._dead_letter(
                message,
                headers,
                routing_key,
                "validation_error",
                str(exc),
            )
            if published:
                await message.ack()
                self._metrics.consumer_dead_lettered.add(
                    1,
                    {EVENT_TYPE_ATTRIBUTE: routing_key},
                )
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._metrics.consumer_failures.add(1, {EVENT_TYPE_ATTRIBUTE: routing_key})
            if should_dead_letter(
                headers,
                self._settings.rabbitmq_retry_max_attempts,
                QueueName.NOTIFICATION_RESULTS.value,
            ):
                published = await self._dead_letter(
                    message,
                    headers,
                    routing_key,
                    "retry_exhausted",
                    str(exc),
                )
                if published:
                    await message.ack()
                    self._metrics.consumer_dead_lettered.add(
                        1,
                        {EVENT_TYPE_ATTRIBUTE: routing_key},
                    )
            else:
                await message.nack(requeue=False)
                self._metrics.consumer_retries.add(1, {EVENT_TYPE_ATTRIBUTE: routing_key})
            logger.exception("Ошибка обработки результата %s", routing_key)
        else:
            self._last_error = None
            await message.ack()
        finally:
            self._active_handlers -= 1
            if self._active_handlers == 0:
                self._idle.set()
            self._metrics.consumer_duration.record(
                time.monotonic() - started_at,
                {EVENT_TYPE_ATTRIBUTE: routing_key},
            )
            reset_correlation_id(token)

    async def _dispatch(
        self,
        command: MessageSent | MessageFailed,
        correlation_id: str,
    ) -> None:
        """Передать результат в сценарий обработки."""
        context = RequestContext(
            correlation_id=correlation_id,
            trace_id=_current_trace_id(),
        )
        if isinstance(command, MessageSent):
            await self._service.handle_sent(command, context)
            return
        await self._service.handle_failed(command, context)

    async def _dead_letter(
        self,
        message: AbstractIncomingMessage,
        headers: Mapping[str, Any],
        routing_key: str,
        error_type: str,
        error_message: str,
    ) -> bool:
        """Опубликовать сообщение в dead-letter очередь."""
        dead_headers: dict[str, str] = {
            "correlation_id": str(headers.get("correlation_id", "")),
            ORIGINAL_ROUTING_KEY_HEADER: routing_key,
            ERROR_TYPE_HEADER: error_type,
            ERROR_MESSAGE_HEADER: error_message[:1000],
            ATTEMPTS_HEADER: str(retry_attempts(headers, QueueName.NOTIFICATION_RESULTS.value)),
        }
        try:
            await self._publisher.publish(
                exchange=EVENTS_EXCHANGE,
                routing_key=f"{QueueName.NOTIFICATION_RESULTS.value}.dlq",
                payload=decode_for_dead_letter(message.body),
                headers=dead_headers,
            )
        except Exception:
            logger.exception("Не удалось опубликовать сообщение в DLQ, возврат в очередь")
            await message.nack(requeue=True)
            return False
        logger.error("Сообщение %s отправлено в DLQ: %s", routing_key, error_message)
        return True


def _current_trace_id() -> str | None:
    """Вернуть идентификатор текущего OTel-трейса."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return format(span_context.trace_id, "032x")
