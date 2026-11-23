"""Проверка структурированных логов заглушки АБС."""

import json
import logging
import sys

from fastapi.testclient import TestClient
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, use_span

from abs.adapters.http.constants import HEALTH_PATH
from abs.config import Settings
from abs.infrastructure.logging import JsonFormatter
from abs.main import create_app


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
    """Создать форматтер с тестовыми общими полями."""
    return JsonFormatter(service="abs", environment="test", service_version="0.1.0")


def test_formatter_includes_common_and_page_fields() -> None:
    """Форматтер добавляет общие поля и атрибуты выгрузки."""
    record = logging.LogRecord(
        name="abs.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Страница выгрузки должников",
        args=(),
        exc_info=None,
    )
    record.event = "debtors_page"
    record.page = 1
    record.page_size = 5
    record.debtor_count = 5
    record.scenario = "ok"

    payload = json.loads(_formatter().format(record))

    assert payload["service"] == "abs"
    assert payload["service_version"] == "0.1.0"
    assert payload["environment"] == "test"
    assert payload["event"] == "debtors_page"
    assert payload["page"] == 1
    assert payload["page_size"] == 5
    assert payload["debtor_count"] == 5
    assert payload["scenario"] == "ok"


def test_formatter_does_not_leak_personal_data() -> None:
    """Произвольные поля с именем и адресом не попадают в лог."""
    record = logging.LogRecord(
        name="abs",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request",
        args=(),
        exc_info=None,
    )
    record.full_name = "Тестовый Должник 01"
    record.address = "debtor01@example.test"

    payload = json.loads(_formatter().format(record))

    assert "full_name" not in payload
    assert "address" not in payload


def test_formatter_includes_trace_context() -> None:
    """Форматтер добавляет trace_id и span_id активного спана."""
    span_context = SpanContext(
        trace_id=0x1234567890ABCDEF1234567890ABCDEF,
        span_id=0x1234567890ABCDEF,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    record = logging.LogRecord(
        name="abs.access",
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
            name="abs",
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


def test_access_log_skips_health_and_logs_unmatched_route() -> None:
    """Access-лог не пишется для health, но пишется для неизвестного маршрута."""
    app = create_app(Settings(service_name="abs", otel_enabled=False))
    handler = ListHandler()
    logger = logging.getLogger("abs.access")
    logger.addHandler(handler)
    try:
        with TestClient(app) as client:
            client.get(HEALTH_PATH)
            client.get("/missing")
    finally:
        logger.removeHandler(handler)

    assert len(handler.records) == 1
    values = vars(handler.records[0])
    assert values["http_route"] == "unmatched"
    assert values["http_status_code"] == 404
    assert values["http_method"] == "GET"
    assert values["event"] == "http_request"
    assert isinstance(values["duration_ms"], float)
