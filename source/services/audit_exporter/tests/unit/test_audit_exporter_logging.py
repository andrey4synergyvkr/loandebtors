"""Проверка структурированных логов Audit Exporter."""

import json
import logging
import sys

from fastapi.testclient import TestClient
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, use_span

from audit_exporter.adapters.http.constants import AUDIT_RECORDS_PATH, HEALTH_PATH
from audit_exporter.application.audit_reader import RequestContext
from audit_exporter.config import Settings
from audit_exporter.domain import AuditFilter, AuditPage
from audit_exporter.infrastructure.logging import JsonFormatter
from audit_exporter.main import create_app


class ListHandler(logging.Handler):
    """Сохраняет записи логов для проверки."""

    def __init__(self) -> None:
        """Создать пустой список записей."""
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Добавить запись в список."""
        self.records.append(record)


class EmptyReader:
    """Читатель, который возвращает пустую страницу."""

    async def list_records(self, filters: AuditFilter, context: RequestContext) -> AuditPage:
        """Вернуть пустую страницу журнала."""
        return AuditPage(items=(), next_cursor=None)


def _formatter() -> JsonFormatter:
    return JsonFormatter(service="audit_exporter", environment="test", service_version="0.1.0")


def test_formatter_includes_common_and_extra_fields() -> None:
    """Форматтер добавляет общие поля и audit-атрибуты."""
    record = logging.LogRecord(
        name="audit_exporter.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="HTTP %s %s %s",
        args=("GET", AUDIT_RECORDS_PATH, 200),
        exc_info=None,
    )
    record.event = "http_request"
    record.http_method = "GET"
    record.http_route = AUDIT_RECORDS_PATH
    record.http_status_code = 200
    record.duration_ms = 1.25
    record.event_id = "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d"
    record.action = "message.sent"
    record.source_service = "email_channel"
    record.sequence = 7
    record.records_returned = 2

    payload = json.loads(_formatter().format(record))

    assert payload["message"] == f"HTTP GET {AUDIT_RECORDS_PATH} 200"
    assert payload["service"] == "audit_exporter"
    assert payload["service_version"] == "0.1.0"
    assert payload["environment"] == "test"
    assert payload["event"] == "http_request"
    assert payload["http_route"] == AUDIT_RECORDS_PATH
    assert payload["event_id"] == "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d"
    assert payload["action"] == "message.sent"
    assert payload["source_service"] == "email_channel"
    assert payload["sequence"] == 7
    assert payload["records_returned"] == 2


def test_formatter_includes_trace_context() -> None:
    """Форматтер добавляет trace_id и span_id активного спана."""
    span_context = SpanContext(
        trace_id=0x1234567890ABCDEF1234567890ABCDEF,
        span_id=0x1234567890ABCDEF,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    record = logging.LogRecord(
        name="audit_exporter.access",
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
            name="audit_exporter",
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


def test_access_log_contains_http_fields_and_skips_health() -> None:
    """Access-лог пишется для бизнес-маршрута и не пишется для health."""
    app = create_app(
        Settings(
            service_name="audit_exporter",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    app.state.audit_reader = EmptyReader()
    handler = ListHandler()
    logger = logging.getLogger("audit_exporter.access")
    logger.addHandler(handler)
    try:
        with TestClient(app) as client:
            client.get(AUDIT_RECORDS_PATH)
            client.get(HEALTH_PATH)
    finally:
        logger.removeHandler(handler)

    assert len(handler.records) == 1
    values = vars(handler.records[0])
    assert values["http_route"] == AUDIT_RECORDS_PATH
    assert values["http_status_code"] == 200
    assert values["http_method"] == "GET"
    assert values["event"] == "http_request"
    assert isinstance(values["duration_ms"], float)
