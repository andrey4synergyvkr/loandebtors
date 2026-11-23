"""Проверка структурированных логов и маскирования."""

import json
import logging
import sys

from fastapi.testclient import TestClient
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, use_span

from notifications.adapters.http.constants import CAMPAIGNS_PATH, HEALTH_PATH
from notifications.config import Settings
from notifications.infrastructure.logging import JsonFormatter
from notifications.infrastructure.masking import mask_email
from notifications.main import create_app


class ListHandler(logging.Handler):
    """Сохраняет записи логов для проверки."""

    def __init__(self) -> None:
        """Создать пустой список записей."""
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Добавить запись в список."""
        self.records.append(record)


def _formatter() -> JsonFormatter:
    return JsonFormatter(service="notifications", environment="test", service_version="0.1.0")


def test_formatter_includes_common_and_extra_fields() -> None:
    """Форматтер добавляет общие поля, корреляцию и HTTP-атрибуты."""
    record = logging.LogRecord(
        name="notifications.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="HTTP %s %s %s",
        args=("GET", CAMPAIGNS_PATH, 501),
        exc_info=None,
    )
    record.event = "http_request"
    record.http_method = "GET"
    record.http_route = CAMPAIGNS_PATH
    record.http_status_code = 501
    record.duration_ms = 1.25

    payload = json.loads(_formatter().format(record))

    assert payload["message"] == f"HTTP GET {CAMPAIGNS_PATH} 501"
    assert payload["service"] == "notifications"
    assert payload["service_version"] == "0.1.0"
    assert payload["environment"] == "test"
    assert payload["event"] == "http_request"
    assert payload["http_method"] == "GET"
    assert payload["http_route"] == CAMPAIGNS_PATH
    assert payload["http_status_code"] == 501
    assert payload["duration_ms"] == 1.25


def test_formatter_includes_trace_context() -> None:
    """Форматтер добавляет trace_id и span_id активного спана."""
    span_context = SpanContext(
        trace_id=0x1234567890ABCDEF1234567890ABCDEF,
        span_id=0x1234567890ABCDEF,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    record = logging.LogRecord(
        name="notifications.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request",
        args=(),
        exc_info=None,
    )

    with use_span(NonRecordingSpan(span_context), end_on_exit=False):
        payload = json.loads(_formatter().format(record))

    assert payload["trace_id"] == "1234567890abcdef1234567890abcdef"
    assert payload["span_id"] == "1234567890abcdef"


def test_formatter_includes_exception_type() -> None:
    """Форматтер добавляет тип исключения."""
    try:
        raise ValueError("ошибка")
    except ValueError:
        record = logging.LogRecord(
            name="notifications",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failure",
            args=(),
            exc_info=sys.exc_info(),
        )
        payload = json.loads(_formatter().format(record))

    assert payload["exception_type"] == "ValueError"
    assert "ValueError: ошибка" in payload["exception"]


def test_mask_email() -> None:
    """Маскирование сохраняет домен и скрывает локальную часть."""
    assert mask_email("ivan.petrov@example.com") == "i***@example.com"
    assert mask_email("a@example.com") == "***@example.com"
    assert mask_email("not-an-email") == "***"


def test_access_log_contains_http_fields_and_skips_health() -> None:
    """Access-лог пишется для бизнес-маршрута и не пишется для health."""
    app = create_app(
        Settings(
            service_name="notifications",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    handler = ListHandler()
    logger = logging.getLogger("notifications.access")
    logger.addHandler(handler)
    unknown_path = "/v1/unknown"
    try:
        with TestClient(app) as client:
            client.get(unknown_path)
            client.get(HEALTH_PATH)
    finally:
        logger.removeHandler(handler)

    assert len(handler.records) == 1
    values = vars(handler.records[0])
    assert values["http_route"] == "unmatched"
    assert values["http_status_code"] == 404
    assert values["http_method"] == "GET"
    assert values["event"] == "http_request"
    assert isinstance(values["duration_ms"], float)
