"""Проверка HTTP API логических шаблонов."""

from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from notifications.adapters.http.constants import TEMPLATE_PATH, TEMPLATE_VERSION_PATH, TEMPLATES_PATH
from notifications.adapters.http.problems import (
    CONFLICT_CODE,
    CONFLICT_TYPE,
    NOT_FOUND_CODE,
    NOT_FOUND_TYPE,
    VALIDATION_CODE,
    VALIDATION_TYPE,
)
from notifications.config import Settings
from notifications.main import create_app

_TEMPLATE_KEY = "payment-reminder"


@pytest.fixture
def client(template_harness: Any) -> Iterator[TestClient]:
    """Создать приложение с сервисом шаблонов на тестовых двойниках."""
    app = create_app(
        Settings(
            service_name="notifications",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    app.state.template_service = template_harness.service
    with TestClient(app) as test_client:
        yield test_client


def _payload(version: int = 1) -> dict[str, object]:
    """Собрать тело запроса создания шаблона."""
    return {
        "key": _TEMPLATE_KEY,
        "version": version,
        "description": "Напоминание об оплате",
        "required_variables": ["debtor_name", "amount"],
    }


def _create(client: TestClient, version: int = 1) -> dict[str, Any]:
    """Создать шаблон и вернуть ответ."""
    response = client.post(TEMPLATES_PATH, json=_payload(version))
    assert response.status_code == status.HTTP_201_CREATED
    return cast(dict[str, Any], response.json())


def test_create_template_returns_201(client: TestClient) -> None:
    """Создание возвращает draft-версию шаблона."""
    body = _create(client)

    assert body["key"] == _TEMPLATE_KEY
    assert body["version"] == 1
    assert body["status"] == "draft"
    assert body["required_variables"] == ["debtor_name", "amount"]
    assert body["created_at"] == body["updated_at"]


def test_create_duplicate_returns_conflict(client: TestClient) -> None:
    """Повторная версия возвращает 409 Problem."""
    _create(client)

    response = client.post(TEMPLATES_PATH, json=_payload())

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == CONFLICT_TYPE
    assert body["code"] == CONFLICT_CODE
    assert body["status"] == status.HTTP_409_CONFLICT
    assert body["instance"] == TEMPLATES_PATH


def test_create_with_duplicate_variables_returns_422(client: TestClient) -> None:
    """Повторяющиеся переменные отклоняются на уровне схемы."""
    payload = _payload()
    payload["required_variables"] = ["amount", "amount"]

    response = client.post(TEMPLATES_PATH, json=payload)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    body = response.json()
    assert body["type"] == VALIDATION_TYPE
    assert body["code"] == VALIDATION_CODE


def test_get_template_by_version(client: TestClient) -> None:
    """Версия возвращается по номеру."""
    _create(client)

    response = client.get(TEMPLATE_PATH.format(template_key=_TEMPLATE_KEY), params={"version": 1})

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["version"] == 1


def test_get_template_without_version_requires_active(client: TestClient) -> None:
    """Без активной версии запрос возвращает 404."""
    _create(client)

    response = client.get(TEMPLATE_PATH.format(template_key=_TEMPLATE_KEY))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    body = response.json()
    assert body["type"] == NOT_FOUND_TYPE
    assert body["code"] == NOT_FOUND_CODE


def test_activate_template_makes_it_default(client: TestClient) -> None:
    """Активация позволяет получить версию без номера."""
    _create(client)
    path = TEMPLATE_VERSION_PATH.format(template_key=_TEMPLATE_KEY, version=1)

    response = client.patch(path, json={"status": "active"})

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "active"

    default = client.get(TEMPLATE_PATH.format(template_key=_TEMPLATE_KEY))
    assert default.status_code == status.HTTP_200_OK
    assert default.json()["version"] == 1


def test_activate_previous_version_archives_it(client: TestClient) -> None:
    """Активация второй версии архивирует первую."""
    _create(client, version=1)
    _create(client, version=2)
    client.patch(
        TEMPLATE_VERSION_PATH.format(template_key=_TEMPLATE_KEY, version=1),
        json={"status": "active"},
    )

    response = client.patch(
        TEMPLATE_VERSION_PATH.format(template_key=_TEMPLATE_KEY, version=2),
        json={"status": "active"},
    )

    assert response.status_code == status.HTTP_200_OK
    previous = client.get(
        TEMPLATE_PATH.format(template_key=_TEMPLATE_KEY),
        params={"version": 1},
    )
    assert previous.json()["status"] == "archived"


def test_forbidden_transition_returns_conflict(client: TestClient) -> None:
    """Возврат активной версии в draft запрещён."""
    _create(client)
    path = TEMPLATE_VERSION_PATH.format(template_key=_TEMPLATE_KEY, version=1)
    client.patch(path, json={"status": "active"})

    response = client.patch(path, json={"status": "draft"})

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["code"] == CONFLICT_CODE


def test_update_missing_template_returns_404(client: TestClient) -> None:
    """Изменение отсутствующей версии возвращает 404."""
    response = client.patch(
        TEMPLATE_VERSION_PATH.format(template_key="missing", version=1),
        json={"status": "active"},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["type"] == NOT_FOUND_TYPE


def test_list_templates_returns_page(client: TestClient) -> None:
    """Список возвращает страницу и общее число."""
    _create(client, version=1)
    _create(client, version=2)

    response = client.get(TEMPLATES_PATH, params={"status": "draft", "limit": 1, "offset": 0})

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    assert body["items"][0]["version"] == 2


@pytest.mark.parametrize("limit", [0, 201])
def test_list_templates_validates_limit(client: TestClient, limit: int) -> None:
    """Недопустимый limit возвращает 422 Problem."""
    response = client.get(TEMPLATES_PATH, params={"limit": limit})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["type"] == VALIDATION_TYPE


def test_invalid_template_key_in_path_returns_422(client: TestClient) -> None:
    """Ключ в пути проверяется по шаблону контракта."""
    response = client.get(TEMPLATE_PATH.format(template_key="Invalid_Key"))

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["type"] == VALIDATION_TYPE
