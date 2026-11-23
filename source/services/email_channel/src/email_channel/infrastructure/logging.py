"""Структурированное JSON-логирование."""

import json
import logging
from datetime import UTC, datetime
from typing import Final

from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.trace import get_current_span

from email_channel.infrastructure.correlation import get_correlation_id

LOG_TIMESTAMP: Final = "timestamp"
LOG_LEVEL: Final = "level"
LOG_LOGGER: Final = "logger"
LOG_MESSAGE: Final = "message"
LOG_EXCEPTION: Final = "exception"
LOG_EXCEPTION_TYPE: Final = "exception_type"
LOG_SERVICE: Final = "service"
LOG_SERVICE_VERSION: Final = "service_version"
LOG_ENVIRONMENT: Final = "environment"
LOG_CORRELATION_ID: Final = "correlation_id"
LOG_TRACE_ID: Final = "trace_id"
LOG_SPAN_ID: Final = "span_id"

LOG_EXTRA_FIELDS: Final[tuple[str, ...]] = (
    "event",
    "http_method",
    "http_route",
    "http_status_code",
    "duration_ms",
    "channel",
    "outbox_event_type",
)

UVICORN_LOGGERS: Final[tuple[str, ...]] = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
)


class JsonFormatter(logging.Formatter):
    """Форматтер, который пишет одну JSON-запись на строку."""

    def __init__(self, service: str, environment: str, service_version: str) -> None:
        """Сохранить общие поля сервиса для каждой записи."""
        super().__init__()
        self._service = service
        self._environment = environment
        self._service_version = service_version

    def format(self, record: logging.LogRecord) -> str:
        """Сериализовать запись лога в JSON."""
        payload: dict[str, object] = {
            LOG_TIMESTAMP: datetime.now(UTC).isoformat(),
            LOG_LEVEL: record.levelname,
            LOG_LOGGER: record.name,
            LOG_MESSAGE: record.getMessage(),
            LOG_SERVICE: self._service,
            LOG_SERVICE_VERSION: self._service_version,
            LOG_ENVIRONMENT: self._environment,
        }
        correlation_id = get_correlation_id()
        if correlation_id is not None:
            payload[LOG_CORRELATION_ID] = correlation_id

        span_context = get_current_span().get_span_context()
        if span_context.is_valid:
            payload[LOG_TRACE_ID] = format(span_context.trace_id, "032x")
            payload[LOG_SPAN_ID] = format(span_context.span_id, "016x")

        for field_name in LOG_EXTRA_FIELDS:
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value

        if record.exc_info is not None:
            exception_type = record.exc_info[0]
            if exception_type is not None:
                payload[LOG_EXCEPTION_TYPE] = exception_type.__name__
            payload[LOG_EXCEPTION] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(
    level: str,
    service: str,
    environment: str,
    service_version: str,
    logger_provider: LoggerProvider | None = None,
) -> None:
    """Настроить корневой логгер, uvicorn и экспорт логов в OTel."""
    json_formatter = JsonFormatter(
        service=service,
        environment=environment,
        service_version=service_version,
    )
    handler = logging.StreamHandler()
    handler.setFormatter(json_formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    if logger_provider is not None:
        otel_handler = LoggingHandler(
            level=logging.NOTSET,
            logger_provider=logger_provider,
        )
        otel_handler.setFormatter(json_formatter)
        root.addHandler(otel_handler)
    root.setLevel(level.upper())

    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    # Доступ пишет структурированный HTTP-middleware, а не uvicorn.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
