"""Проверка эндпоинта /health сервиса Notifications."""

from importlib import metadata

from fastapi.testclient import TestClient

from notifications.adapters.http.constants import HEALTH_PATH
from notifications.application.health import (
    APPLICATION_CHECK_NAME,
    APPLICATION_READY_DETAIL,
    HealthStatus,
)
from notifications.config import Settings
from notifications.main import PACKAGE_NAME, create_app


def test_health_returns_honest_status() -> None:
    """Health возвращает состояние, версию и проверку приложения."""
    app = create_app(
        Settings(
            service_name="notifications",
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
    assert payload["service"] == "notifications"
    assert payload["version"] == metadata.version(PACKAGE_NAME)
    assert payload["uptime_seconds"] >= 0
    assert payload["checks"] == [
        {
            "name": APPLICATION_CHECK_NAME,
            "status": HealthStatus.OK.value,
            "detail": APPLICATION_READY_DETAIL,
        }
    ]
