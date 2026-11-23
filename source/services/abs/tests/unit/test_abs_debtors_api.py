"""Проверка HTTP-контракта выгрузки должников."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from abs.adapters.http.constants import DEBTORS_PATH
from abs.config import Settings
from abs.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Создать тестовый клиент заглушки."""
    app = create_app(Settings(service_name="abs", otel_enabled=False))
    with TestClient(app) as test_client:
        yield test_client


def test_first_page_matches_contract_shape(client: TestClient) -> None:
    """Страница содержит поля контракта и данные первого должника."""
    response: Response = client.get(DEBTORS_PATH, params={"page": 1, "page_size": 5})

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"items", "page", "total", "has_next"}
    assert payload["page"] == 1
    assert payload["total"] == 24
    assert payload["has_next"] is True
    assert len(payload["items"]) == 5
    assert set(payload["items"][0]) == {"debtor_id", "full_name", "contacts", "debts"}
    contact = payload["items"][0]["contacts"][0]
    assert set(contact) == {"channel", "address", "is_primary"}
    debt = payload["items"][0]["debts"][0]
    assert set(debt) == {"contract_id", "amount", "due_date", "days_overdue"}
    assert debt["amount"] == {"amount": "12500.00", "currency": "RUB"}
    assert debt["due_date"] == "2025-01-15"


def test_default_pagination_returns_all_debtors(client: TestClient) -> None:
    """Параметры страницы по умолчанию возвращают всю выборку."""
    response: Response = client.get(DEBTORS_PATH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["total"] == 24
    assert len(payload["items"]) == 24
    assert payload["has_next"] is False


def test_filters_are_applied(client: TestClient) -> None:
    """Фильтры по просрочке и каналу уменьшают выборку."""
    by_days: Response = client.get(
        DEBTORS_PATH,
        params={"min_days_overdue": 100, "page_size": 100},
    )
    by_channel: Response = client.get(
        DEBTORS_PATH,
        params={"channel": "sms", "page_size": 100},
    )

    assert by_days.status_code == 200
    assert by_days.json()["total"] == 16
    assert by_channel.status_code == 200
    assert by_channel.json()["total"] == 2


def test_unknown_query_parameter_is_ignored(client: TestClient) -> None:
    """Неизвестный query-параметр не ломает выгрузку."""
    response: Response = client.get(DEBTORS_PATH, params={"portfolio": "main"})

    assert response.status_code == 200
    assert response.json()["total"] == 24


def test_invalid_page_returns_problem(client: TestClient) -> None:
    """Некорректный номер страницы возвращает problem+json."""
    response: Response = client.get(DEBTORS_PATH, params={"page": 0})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    payload = response.json()
    assert payload["type"] == "urn:loandebtors:error:validation"
    assert payload["status"] == 422
    assert payload["code"] == "validation_error"


def test_response_contains_request_id(client: TestClient) -> None:
    """Ответ содержит идентификатор корреляции."""
    response: Response = client.get(DEBTORS_PATH)

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
