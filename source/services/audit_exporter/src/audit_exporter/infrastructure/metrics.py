"""Метрики OpenTelemetry для инфраструктуры сервиса."""

from typing import Final

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, Meter

METER_NAME: Final = "loandebtors.audit_exporter"
AUDIT_INGESTED_METRIC: Final = "loandebtors.audit_exporter.audit.ingested"
AUDIT_INGEST_FAILURES_METRIC: Final = "loandebtors.audit_exporter.audit.ingest.failures"
AUDIT_CONFLICTS_METRIC: Final = "loandebtors.audit_exporter.audit.conflicts"
AUDIT_INGEST_DURATION_METRIC: Final = "loandebtors.audit_exporter.audit.ingest.duration"
AUDIT_DLQ_PUBLISHED_METRIC: Final = "loandebtors.audit_exporter.audit.dlq.published"
AUDIT_RECORDS_RETURNED_METRIC: Final = "loandebtors.audit_exporter.audit.records.returned"
AUDIT_QUERY_DURATION_METRIC: Final = "loandebtors.audit_exporter.audit.query.duration"
HTTP_REQUESTS_METRIC: Final = "loandebtors.audit_exporter.http.requests"
HTTP_DURATION_METRIC: Final = "loandebtors.audit_exporter.http.duration"
QUEUE_MESSAGES_METRIC: Final = "loandebtors.audit_exporter.queue.messages"
CONSUMER_RUNNING_METRIC: Final = "loandebtors.audit_exporter.consumer.running"
CONSUMER_RECONNECTS_METRIC: Final = "loandebtors.audit_exporter.consumer.reconnects"
AUDIT_ACTION_ATTRIBUTE: Final = "audit.action"
AUDIT_REASON_ATTRIBUTE: Final = "audit.reason"
AUDIT_SOURCE_ATTRIBUTE: Final = "audit.source_service"
QUEUE_ATTRIBUTE: Final = "queue"
HTTP_METHOD_ATTRIBUTE: Final = "http.request.method"
HTTP_ROUTE_ATTRIBUTE: Final = "http.route"
HTTP_STATUS_ATTRIBUTE: Final = "http.response.status_code"


class Metrics:
    """Набор инструментов метрик, созданных после настройки OTel."""

    def __init__(self) -> None:
        """Создать счетчики и гистограммы на текущем meter provider."""
        meter: Meter = metrics.get_meter(METER_NAME)
        self.audit_ingested: Counter = meter.create_counter(
            AUDIT_INGESTED_METRIC,
            unit="1",
            description="Количество audit-событий, записанных в журнал",
        )
        self.audit_ingest_failures: Counter = meter.create_counter(
            AUDIT_INGEST_FAILURES_METRIC,
            unit="1",
            description="Количество ошибок приёма audit-событий",
        )
        self.audit_conflicts: Counter = meter.create_counter(
            AUDIT_CONFLICTS_METRIC,
            unit="1",
            description="Количество событий с конфликтом event_id",
        )
        self.audit_ingest_duration: Histogram = meter.create_histogram(
            AUDIT_INGEST_DURATION_METRIC,
            unit="s",
            description="Длительность обработки audit-события",
        )
        self.audit_dlq_published: Counter = meter.create_counter(
            AUDIT_DLQ_PUBLISHED_METRIC,
            unit="1",
            description="Количество сообщений, отправленных в DLQ",
        )
        self.audit_records_returned: Histogram = meter.create_histogram(
            AUDIT_RECORDS_RETURNED_METRIC,
            unit="1",
            description="Размер выданной страницы журнала",
        )
        self.audit_query_duration: Histogram = meter.create_histogram(
            AUDIT_QUERY_DURATION_METRIC,
            unit="s",
            description="Длительность чтения журнала аудита",
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
        self.queue_messages = meter.create_gauge(
            QUEUE_MESSAGES_METRIC,
            unit="1",
            description="Количество сообщений в очереди",
        )
        self.consumer_running = meter.create_gauge(
            CONSUMER_RUNNING_METRIC,
            unit="1",
            description="Признак запущенного консьюмера",
        )
        self.consumer_reconnects: Counter = meter.create_counter(
            CONSUMER_RECONNECTS_METRIC,
            unit="1",
            description="Количество переподключений консьюмера",
        )
