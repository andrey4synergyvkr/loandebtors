"""Интеграционная проверка запуска Audit Exporter с зависимостями."""

import httpx
import pytest

from audit_exporter.adapters.http.constants import HEALTH_PATH
from audit_exporter.application.health import (
    APPLICATION_CHECK_NAME,
    AUDIT_CONSUMER_CHECK_NAME,
    DATABASE_CHECK_NAME,
    RABBITMQ_CHECK_NAME,
)

pytestmark = pytest.mark.integration

_REQUEST_TIMEOUT_SECONDS = 5.0


def test_service_starts_with_dependencies_and_returns_health(audit_exporter_url: str) -> None:
    """Сервис поднимается с PostgreSQL, RabbitMQ и консьюмером."""
    response = httpx.get(
        f"{audit_exporter_url}{HEALTH_PATH}",
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "audit_exporter"
    assert payload["version"]
    assert payload["uptime_seconds"] >= 0
    checks = {check["name"]: check["status"] for check in payload["checks"]}
    assert checks[APPLICATION_CHECK_NAME] == "ok"
    assert checks[DATABASE_CHECK_NAME] == "ok"
    assert checks[RABBITMQ_CHECK_NAME] == "ok"
    assert checks[AUDIT_CONSUMER_CHECK_NAME] == "ok"
