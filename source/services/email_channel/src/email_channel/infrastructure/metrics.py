"""Метрики OpenTelemetry для инфраструктуры сервиса."""

from typing import Final

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, Meter

METER_NAME: Final = "loandebtors.email_channel"
OUTBOX_PUBLISHED_METRIC: Final = "loandebtors.email_channel.outbox.published"
OUTBOX_FAILURES_METRIC: Final = "loandebtors.email_channel.outbox.failures"
OUTBOX_ERRORS_METRIC: Final = "loandebtors.email_channel.outbox.errors"
OUTBOX_BATCH_SIZE_METRIC: Final = "loandebtors.email_channel.outbox.batch.size"
OUTBOX_PROCESSING_DURATION_METRIC: Final = "loandebtors.email_channel.outbox.processing.duration"
HTTP_REQUESTS_METRIC: Final = "loandebtors.email_channel.http.requests"
HTTP_DURATION_METRIC: Final = "loandebtors.email_channel.http.duration"
EMAIL_SENT_METRIC: Final = "loandebtors.email_channel.email.sent"
EMAIL_FAILED_METRIC: Final = "loandebtors.email_channel.email.failed"
EMAIL_DUPLICATES_METRIC: Final = "loandebtors.email_channel.email.duplicates"
EMAIL_COMMAND_FAILURES_METRIC: Final = "loandebtors.email_channel.email.command.failures"
EMAIL_SEND_DURATION_METRIC: Final = "loandebtors.email_channel.email.send.duration"
CONSUMER_RECONNECTS_METRIC: Final = "loandebtors.email_channel.consumer.reconnects"
CONSUMER_RUNNING_METRIC: Final = "loandebtors.email_channel.consumer.running"
EVENT_TYPE_ATTRIBUTE: Final = "event_type"
DELIVERY_OUTCOME_ATTRIBUTE: Final = "delivery.outcome"
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
        self.email_sent: Counter = meter.create_counter(
            EMAIL_SENT_METRIC,
            unit="1",
            description="Количество отправленных писем",
        )
        self.email_failed: Counter = meter.create_counter(
            EMAIL_FAILED_METRIC,
            unit="1",
            description="Количество писем с ошибкой отправки",
        )
        self.email_duplicates: Counter = meter.create_counter(
            EMAIL_DUPLICATES_METRIC,
            unit="1",
            description="Количество повторно доставленных сообщений",
        )
        self.email_command_failures: Counter = meter.create_counter(
            EMAIL_COMMAND_FAILURES_METRIC,
            unit="1",
            description="Количество ошибок обработки message.send",
        )
        self.email_send_duration: Histogram = meter.create_histogram(
            EMAIL_SEND_DURATION_METRIC,
            unit="s",
            description="Длительность обработки message.send",
        )
        self.consumer_reconnects: Counter = meter.create_counter(
            CONSUMER_RECONNECTS_METRIC,
            unit="1",
            description="Количество переподключений консьюмера",
        )
        self.consumer_running = meter.create_gauge(
            CONSUMER_RUNNING_METRIC,
            unit="1",
            description="Признак запущенного консьюмера",
        )
