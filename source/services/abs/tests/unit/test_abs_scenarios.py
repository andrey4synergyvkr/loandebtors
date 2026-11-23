"""Проверка управляемых сценариев заглушки."""

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from abs.adapters.http.constants import DEBTORS_PATH
from abs.config import Settings
from abs.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Создать тестовый клиент с короткой задержкой таймаута."""
    app = create_app(
        Settings(
            service_name="abs",
            otel_enabled=False,
            stub_timeout_seconds=0.2,
        )
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("scenario", "status", "code"),
    [
        ("unavailable", 503, "abs_unavailable"),
        ("error_500", 500, "internal_error"),
        ("bad", 400, "invalid_stub_scenario"),
    ],
)
def test_error_scenarios_return_problem(
    client: TestClient,
    scenario: str,
    status: int,
    code: str,
) -> None:
    """Сценарии ошибок возвращают problem+json с ожидаемым кодом."""
    response: Response = client.get(
        DEBTORS_PATH,
        params={"page": 1, "page_size": 5},
        headers={"X-Stub-Scenario": scenario},
    )

    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    payload = response.json()
    assert payload["status"] == status
    assert payload["code"] == code


def test_incomplete_scenario_truncates_page(client: TestClient) -> None:
    """Сценарий incomplete усекает страницу, сохраняя полный total."""
    response: Response = client.get(
        DEBTORS_PATH,
        params={"page": 1, "page_size": 5},
        headers={"X-Stub-Scenario": "incomplete"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 4
    assert payload["total"] == 24
    assert payload["has_next"] is False


def test_timeout_scenario_delays_response(client: TestClient) -> None:
    """Сценарий timeout задерживает ответ на заданное время."""
    started_at = time.monotonic()
    response: Response = client.get(
        DEBTORS_PATH,
        params={"page": 1, "page_size": 5},
        headers={"X-Stub-Scenario": "timeout"},
    )
    elapsed = time.monotonic() - started_at

    assert response.status_code == 200
    assert elapsed >= 0.1


def test_ok_scenario_returns_page(client: TestClient) -> None:
    """Сценарий ok возвращает обычную страницу."""
    response: Response = client.get(
        DEBTORS_PATH,
        params={"page": 1, "page_size": 5},
        headers={"X-Stub-Scenario": "ok"},
    )

    assert response.status_code == 200
    assert len(response.json()["items"]) == 5
