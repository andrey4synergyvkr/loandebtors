"""Смоук-сценарий каркаса: проверка эндпоинта /health."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pytest_bdd import given, scenario, then, when

from notifications.adapters.http.constants import HEALTH_PATH
from notifications.application.health import APPLICATION_CHECK_NAME
from notifications.config import Settings
from notifications.main import create_app

pytestmark = pytest.mark.bdd


@scenario("features/health.feature", "Эндпоинт health сообщает состояние сервиса")
def test_health_endpoint() -> None:
    """Сценарий выполняется шагами ниже."""


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Создать тестовый клиент Notifications."""
    app = create_app(
        Settings(
            service_name="notifications",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    with TestClient(app) as test_client:
        yield test_client


@given("сервис notifications запущен")
def service_is_running(client: TestClient) -> None:
    """Подготовить запущенный клиент сервиса."""
    assert client is not None


@when("запрашивается эндпоинт health", target_fixture="response")
def request_health(client: TestClient) -> Response:
    """Запросить эндпоинт health."""
    response: Response = client.get(HEALTH_PATH)
    return response


@then('ответ имеет статус "ok", сервис "notifications" и успешную проверку "application"')
def check_health(response: Response) -> None:
    """Проверить статус, имя сервиса и проверку application."""
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "notifications"
    assert payload["uptime_seconds"] >= 0
    assert payload["checks"][0]["name"] == APPLICATION_CHECK_NAME
    assert payload["checks"][0]["status"] == "ok"
