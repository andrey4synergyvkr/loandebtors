"""Метрики OpenTelemetry для инфраструктуры сервиса."""

from typing import Final

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, Meter

METER_NAME: Final = "loandebtors.scheduler"
OUTBOX_PUBLISHED_METRIC: Final = "loandebtors.scheduler.outbox.published"
OUTBOX_FAILURES_METRIC: Final = "loandebtors.scheduler.outbox.failures"
OUTBOX_ERRORS_METRIC: Final = "loandebtors.scheduler.outbox.errors"
OUTBOX_BATCH_SIZE_METRIC: Final = "loandebtors.scheduler.outbox.batch.size"
OUTBOX_PROCESSING_DURATION_METRIC: Final = "loandebtors.scheduler.outbox.processing.duration"
HTTP_REQUESTS_METRIC: Final = "loandebtors.scheduler.http.requests"
HTTP_DURATION_METRIC: Final = "loandebtors.scheduler.http.duration"
CONSUMER_MESSAGES_METRIC: Final = "loandebtors.scheduler.consumer.messages"
CONSUMER_FAILURES_METRIC: Final = "loandebtors.scheduler.consumer.failures"
CONSUMER_RETRIES_METRIC: Final = "loandebtors.scheduler.consumer.retries"
CONSUMER_DEAD_LETTERED_METRIC: Final = "loandebtors.scheduler.consumer.dead_lettered"
CONSUMER_DURATION_METRIC: Final = "loandebtors.scheduler.consumer.duration"
JOBS_REGISTERED_METRIC: Final = "loandebtors.scheduler.jobs.registered"
JOBS_TRIGGERED_METRIC: Final = "loandebtors.scheduler.jobs.triggered"
RECOVERY_FAILURES_METRIC: Final = "loandebtors.scheduler.jobs.recovery_failures"
EVENT_TYPE_ATTRIBUTE: Final = "event_type"
HTTP_METHOD_ATTRIBUTE: Final = "http.request.method"
HTTP_ROUTE_ATTRIBUTE: Final = "http.route"
HTTP_STATUS_ATTRIBUTE: Final = "http.response.status_code"


class Metrics:
    """Набор инструментов метрик, созданных после настройки OTel."""

    def __init__(self) -> None:
        """Создать счетчики и гистограммы на текущем meter provider."""
        meter: Meter = metrics.get_meter(METER_NAME)
        self.outbox_published: Counter = meter.create_counter(
            OUTBOX_PUBLISHED_METRIC,
            unit="1",
            description="Количество опубликованных записей outbox",
        )
        self.outbox_failures: Counter = meter.create_counter(
            OUTBOX_FAILURES_METRIC,
            unit="1",
            description="Количество ошибок публикации outbox",
        )
        self.outbox_errors: Counter = meter.create_counter(
            OUTBOX_ERRORS_METRIC,
            unit="1",
            description="Количество ошибок чтения или обновления outbox",
        )
        self.outbox_batch_size: Histogram = meter.create_histogram(
            OUTBOX_BATCH_SIZE_METRIC,
            unit="1",
            description="Размер обработанной пачки outbox",
        )
        self.outbox_processing_duration: Histogram = meter.create_histogram(
            OUTBOX_PROCESSING_DURATION_METRIC,
            unit="s",
            description="Длительность обработки пачки outbox",
        )
        self.http_requests: Counter = meter.create_counter(
            HTTP_REQUESTS_METRIC,
            unit="1",
            description="Количество HTTP-запросов",
        )
        self.http_duration: Histogram = meter.create_histogram(
            HTTP_DURATION_METRIC,
            unit="s",
            description="Длительность HTTP-запроса",
        )
        self.consumer_messages: Counter = meter.create_counter(
            CONSUMER_MESSAGES_METRIC,
            unit="1",
            description="Количество принятых команд планировщика",
        )
        self.consumer_failures: Counter = meter.create_counter(
            CONSUMER_FAILURES_METRIC,
            unit="1",
            description="Количество ошибок обработки команд",
        )
        self.consumer_retries: Counter = meter.create_counter(
            CONSUMER_RETRIES_METRIC,
            unit="1",
            description="Количество сообщений, возвращенных в retry-очередь",
        )
        self.consumer_dead_lettered: Counter = meter.create_counter(
            CONSUMER_DEAD_LETTERED_METRIC,
            unit="1",
            description="Количество сообщений, отправленных в DLQ",
        )
        self.consumer_duration: Histogram = meter.create_histogram(
            CONSUMER_DURATION_METRIC,
            unit="s",
            description="Длительность обработки команды",
        )
        self.jobs_registered: Counter = meter.create_counter(
            JOBS_REGISTERED_METRIC,
            unit="1",
            description="Количество зарегистрированных заданий",
        )
        self.jobs_triggered: Counter = meter.create_counter(
            JOBS_TRIGGERED_METRIC,
            unit="1",
            description="Количество срабатываний заданий",
        )
        self.recovery_failures: Counter = meter.create_counter(
            RECOVERY_FAILURES_METRIC,
            unit="1",
            description="Количество ошибок восстановления заданий",
        )
