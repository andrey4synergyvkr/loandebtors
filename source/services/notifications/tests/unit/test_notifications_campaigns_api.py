"""Проверка HTTP API кампаний."""

from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from notifications.adapters.http.constants import (
    CAMPAIGN_PATH,
    CAMPAIGNS_PATH,
    TEMPLATE_VERSION_PATH,
    TEMPLATES_PATH,
)
from notifications.adapters.http.problems import (
    CONFLICT_CODE,
    CONFLICT_TYPE,
    NOT_FOUND_TYPE,
    VALIDATION_TYPE,
)
from notifications.config import Settings
from notifications.domain import CampaignStatus
from notifications.main import create_app

_TEMPLATE_KEY = "payment-reminder"


@pytest.fixture
def client(campaign_harness: Any) -> Iterator[TestClient]:
    """Создать приложение с сервисами на тестовых двойниках."""
    app = create_app(
        Settings(
            service_name="notifications",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    app.state.template_service = campaign_harness.service
    app.state.campaign_service = campaign_harness.campaign_service
    app.state.test_harness = campaign_harness
    with TestClient(app) as test_client:
        yield test_client


def _create_active_template(client: TestClient, version: int = 1) -> None:
    """Создать и активировать шаблон через API."""
    response = client.post(
        TEMPLATES_PATH,
        json={
            "key": _TEMPLATE_KEY,
            "version": version,
            "description": "Шаблон для кампании",
            "required_variables": ["debtor_name", "amount"],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    response = client.patch(
        TEMPLATE_VERSION_PATH.format(template_key=_TEMPLATE_KEY, version=version),
        json={"status": "active"},
    )
    assert response.status_code == status.HTTP_200_OK


def _payload(version: int = 1) -> dict[str, object]:
    """Собрать тело запроса создания кампании."""
    return {
        "name": "Напоминание о просрочке",
        "channel": "email",
        "template_key": _TEMPLATE_KEY,
        "template_version": version,
        "selection": {"criteria": {"min_days_overdue": "30"}},
    }


def _create_campaign(client: TestClient, version: int = 1) -> dict[str, Any]:
    """Создать кампанию и вернуть тело ответа."""
    response = client.post(CAMPAIGNS_PATH, json=_payload(version))
    assert response.status_code == status.HTTP_201_CREATED
    return cast(dict[str, Any], response.json())


def test_create_campaign_returns_draft(client: TestClient) -> None:
    """Создание возвращает кампанию в статусе draft."""
    _create_active_template(client)

    body = _create_campaign(client)

    assert body["status"] == "draft"
    assert body["channel"] == "email"
    assert body["template_key"] == _TEMPLATE_KEY
    assert body["template_version"] == 1
    assert body["selection"] == {"criteria": {"min_days_overdue": "30"}}
    assert body["schedule"] is None
    assert body["selected_debtors"] == 0
    assert body["selection_expected"] is None


def test_create_campaign_requires_active_template(client: TestClient) -> None:
    """Неактивный шаблон дает 409 Problem."""
    client.post(
        TEMPLATES_PATH,
        json={
            "key": _TEMPLATE_KEY,
            "version": 1,
            "description": "Черновик шаблона",
            "required_variables": ["debtor_name"],
        },
    )

    response = client.post(CAMPAIGNS_PATH, json=_payload())

    assert response.status_code == status.HTTP_409_CONFLICT
    body = response.json()
    assert body["type"] == CONFLICT_TYPE
    assert body["code"] == CONFLICT_CODE
    assert body["instance"] == CAMPAIGNS_PATH


def test_create_campaign_rejects_non_email_channel(client: TestClient) -> None:
    """Доменный отказ по каналу возвращает 422 Problem."""
    _create_active_template(client)
    payload = _payload()
    payload["channel"] = "sms"

    response = client.post(CAMPAIGNS_PATH, json=payload)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["type"] == VALIDATION_TYPE


def test_create_campaign_rejects_empty_selection_body(client: TestClient) -> None:
    """Отсутствующая выборка отклоняется схемой."""
    _create_active_template(client)
    payload = _payload()
    del payload["selection"]

    response = client.post(CAMPAIGNS_PATH, json=payload)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["type"] == VALIDATION_TYPE


def test_get_campaign(client: TestClient) -> None:
    """Кампания возвращается по идентификатору."""
    _create_active_template(client)
    created = _create_campaign(client)

    response = client.get(CAMPAIGN_PATH.format(campaign_id=created["id"]))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == created["id"]


def test_get_missing_campaign_returns_404(client: TestClient) -> None:
    """Отсутствующая кампания возвращает 404 Problem."""
    response = client.get(CAMPAIGN_PATH.format(campaign_id=uuid4()))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["type"] == NOT_FOUND_TYPE


def test_get_campaign_with_invalid_uuid_returns_422(client: TestClient) -> None:
    """Некорректный идентификатор отклоняется схемой."""
    response = client.get(CAMPAIGN_PATH.format(campaign_id="not-a-uuid"))

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["type"] == VALIDATION_TYPE


def test_list_campaigns_filters_by_status(client: TestClient) -> None:
    """Список фильтрует кампании по статусу."""
    _create_active_template(client)
    _create_campaign(client)

    response = client.get(CAMPAIGNS_PATH, params={"status": "draft", "limit": 10, "offset": 0})

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "draft"


def test_update_campaign_name(client: TestClient) -> None:
    """PATCH меняет имя draft-кампании."""
    _create_active_template(client)
    created = _create_campaign(client)

    response = client.patch(
        CAMPAIGN_PATH.format(campaign_id=created["id"]),
        json={"name": "Новое имя"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "Новое имя"


def test_update_campaign_with_single_template_field_returns_422(
    client: TestClient,
) -> None:
    """Ключ и версия шаблона передаются вместе."""
    _create_active_template(client)
    created = _create_campaign(client)

    response = client.patch(
        CAMPAIGN_PATH.format(campaign_id=created["id"]),
        json={"template_key": _TEMPLATE_KEY},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["type"] == VALIDATION_TYPE


def test_update_campaign_with_empty_body_returns_422(client: TestClient) -> None:
    """Пустой PATCH отклоняется схемой."""
    _create_active_template(client)
    created = _create_campaign(client)

    response = client.patch(CAMPAIGN_PATH.format(campaign_id=created["id"]), json={})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["type"] == VALIDATION_TYPE


def test_update_non_draft_campaign_returns_conflict(client: TestClient) -> None:
    """Кампанию вне draft изменить нельзя."""
    harness: Any = cast(Any, client.app).state.test_harness
    _create_active_template(client)
    created = _create_campaign(client)
    campaign = harness.campaigns.items[UUID(created["id"])]
    campaign.status = CampaignStatus.RUNNING

    response = client.patch(
        CAMPAIGN_PATH.format(campaign_id=created["id"]),
        json={"name": "Новое имя"},
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["code"] == CONFLICT_CODE
