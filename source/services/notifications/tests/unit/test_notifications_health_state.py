"""Проверка состояний health сервиса Notifications."""

from fastapi.testclient import TestClient

from notifications.adapters.http.constants import HEALTH_PATH
from notifications.application.health import (
    APPLICATION_CHECK_NAME,
    APPLICATION_SHUTTING_DOWN_DETAIL,
    ApplicationState,
    HealthService,
    HealthStatus,
)
from notifications.config import Settings
from notifications.main import create_app


def test_application_state_starts_unavailable() -> None:
    """До вызова mark_ready приложение не считается готовым."""
    state = ApplicationState(service="notifications", version="0.1.0")
    snapshot = state.snapshot()

    assert snapshot.status is HealthStatus.UNAVAILABLE
    assert snapshot.checks[0].name == APPLICATION_CHECK_NAME
    assert snapshot.checks[0].status is HealthStatus.UNAVAILABLE


def test_health_returns_503_when_shutting_down() -> None:
    """При остановке health отвечает 503 и статусом unavailable."""
    app = create_app(
        Settings(
            service_name="notifications",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    with TestClient(app) as client:
        state: HealthService = app.state.health
        state.begin_shutdown()
        response = client.get(HEALTH_PATH)

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == HealthStatus.UNAVAILABLE.value
    assert payload["checks"] == [
        {
            "name": APPLICATION_CHECK_NAME,
            "status": HealthStatus.UNAVAILABLE.value,
            "detail": APPLICATION_SHUTTING_DOWN_DETAIL,
        }
    ]
