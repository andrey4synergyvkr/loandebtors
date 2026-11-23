"""Проверка эндпоинта /health сервиса Audit Exporter."""

from importlib import metadata

from fastapi.testclient import TestClient

from audit_exporter.adapters.http.constants import HEALTH_PATH
from audit_exporter.application.health import (
    APPLICATION_CHECK_NAME,
    APPLICATION_READY_DETAIL,
    HealthStatus,
)
from audit_exporter.config import Settings
from audit_exporter.main import PACKAGE_NAME, create_app


def test_health_returns_honest_status() -> None:
    """Health возвращает состояние, версию и проверку приложения."""
    app = create_app(
        Settings(
            service_name="audit_exporter",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    with TestClient(app) as client:
        response = client.get(HEALTH_PATH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == HealthStatus.OK.value
    assert payload["service"] == "audit_exporter"
    assert payload["version"] == metadata.version(PACKAGE_NAME)
    assert payload["uptime_seconds"] >= 0
    assert payload["checks"] == [
        {
            "name": APPLICATION_CHECK_NAME,
            "status": HealthStatus.OK.value,
            "detail": APPLICATION_READY_DETAIL,
        }
    ]
