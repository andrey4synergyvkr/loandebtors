"""Метрики OpenTelemetry для инфраструктуры сервиса."""

from typing import Final

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, Meter

METER_NAME: Final = "loandebtors.notifications"
OUTBOX_PUBLISHED_METRIC: Final = "loandebtors.notifications.outbox.published"
OUTBOX_FAILURES_METRIC: Final = "loandebtors.notifications.outbox.failures"
OUTBOX_ERRORS_METRIC: Final = "loandebtors.notifications.outbox.errors"
OUTBOX_BATCH_SIZE_METRIC: Final = "loandebtors.notifications.outbox.batch.size"
OUTBOX_PROCESSING_DURATION_METRIC: Final = "loandebtors.notifications.outbox.processing.duration"
HTTP_REQUESTS_METRIC: Final = "loandebtors.notifications.http.requests"
HTTP_DURATION_METRIC: Final = "loandebtors.notifications.http.duration"
CONSUMER_MESSAGES_METRIC: Final = "loandebtors.notifications.consumer.messages"
CONSUMER_FAILURES_METRIC: Final = "loandebtors.notifications.consumer.failures"
CONSUMER_RETRIES_METRIC: Final = "loandebtors.notifications.consumer.retries"
CONSUMER_DEAD_LETTERED_METRIC: Final = "loandebtors.notifications.consumer.dead_lettered"
CONSUMER_DURATION_METRIC: Final = "loandebtors.notifications.consumer.duration"
CAMPAIGN_DEBTORS_METRIC: Final = "loandebtors.notifications.campaign.debtors"
CAMPAIGN_MESSAGES_METRIC: Final = "loandebtors.notifications.campaign.messages"
MAINTENANCE_REQUEUED_METRIC: Final = "loandebtors.notifications.maintenance.requeued"
MAINTENANCE_COMPLETED_METRIC: Final = "loandebtors.notifications.maintenance.completed"
MAINTENANCE_EXHAUSTED_METRIC: Final = "loandebtors.notifications.maintenance.exhausted"
MAINTENANCE_DELETED_METRIC: Final = "loandebtors.notifications.maintenance.deleted"
MAINTENANCE_TABLE_ATTRIBUTE: Final = "table"
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
            description="Количество полученных команд",
        )
        self.consumer_failures: Counter = meter.create_counter(
            CONSUMER_FAILURES_METRIC,
            unit="1",
            description="Количество ошибок обработки команд",
        )
        self.consumer_retries: Counter = meter.create_counter(
            CONSUMER_RETRIES_METRIC,
            unit="1",
            description="Количество команд, отправленных на повтор",
        )
        self.consumer_dead_lettered: Counter = meter.create_counter(
            CONSUMER_DEAD_LETTERED_METRIC,
            unit="1",
            description="Количество команд, отправленных в DLQ",
        )
        self.consumer_duration: Histogram = meter.create_histogram(
            CONSUMER_DURATION_METRIC,
            unit="s",
            description="Длительность обработки команды",
        )
        self.campaign_debtors: Histogram = meter.create_histogram(
            CAMPAIGN_DEBTORS_METRIC,
            unit="1",
            description="Размер полной выборки должников кампании",
        )
        self.campaign_messages: Histogram = meter.create_histogram(
            CAMPAIGN_MESSAGES_METRIC,
            unit="1",
            description="Количество созданных сообщений кампании",
        )
        self.maintenance_requeued: Counter = meter.create_counter(
            MAINTENANCE_REQUEUED_METRIC,
            unit="1",
            description="Количество повторно поставленных в очередь объектов",
        )
        self.maintenance_completed: Counter = meter.create_counter(
            MAINTENANCE_COMPLETED_METRIC,
            unit="1",
            description="Количество завершенных кампаний при восстановлении",
        )
        self.maintenance_exhausted: Counter = meter.create_counter(
            MAINTENANCE_EXHAUSTED_METRIC,
            unit="1",
            description="Количество сообщений, закрытых из-за отказа публикации outbox",
        )
        self.maintenance_deleted: Counter = meter.create_counter(
            MAINTENANCE_DELETED_METRIC,
            unit="1",
            description="Количество удаленных записей retention",
        )
