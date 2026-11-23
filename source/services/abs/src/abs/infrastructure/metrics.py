"""Метрики OpenTelemetry для HTTP-слоя заглушки."""

from typing import Final

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, Meter

METER_NAME: Final = "loandebtors.abs"
HTTP_REQUESTS_METRIC: Final = "loandebtors.abs.http.requests"
HTTP_DURATION_METRIC: Final = "loandebtors.abs.http.duration"
HTTP_METHOD_ATTRIBUTE: Final = "http.request.method"
HTTP_ROUTE_ATTRIBUTE: Final = "http.route"
HTTP_STATUS_ATTRIBUTE: Final = "http.response.status_code"


class Metrics:
    """Набор инструментов метрик, созданных после настройки OTel."""

    def __init__(self) -> None:
        """Создать счетчики и гистограммы на текущем meter provider."""
        meter: Meter = metrics.get_meter(METER_NAME)
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
