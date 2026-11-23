"""Проверка HTTP API планирования и отмены кампаний."""

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from notifications.adapters.http.constants import (
    CAMPAIGN_CANCEL_PATH,
    CAMPAIGN_SCHEDULE_PATH,
    CAMPAIGNS_PATH,
    TEMPLATE_VERSION_PATH,
    TEMPLATES_PATH,
)
from notifications.adapters.http.problems import (
    CONFLICT_CODE,
    NOT_FOUND_TYPE,
    VALIDATION_TYPE,
)
from notifications.config import Settings
from notifications.main import create_app

_TEMPLATE_KEY = "payment-reminder"
_RUN_AT = "2026-12-01T10:00:00Z"


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
    with TestClient(app) as test_client:
        yield test_client


def _create_active_template(client: TestClient) -> None:
    """Создать и активировать шаблон через API."""
    response = client.post(
        TEMPLATES_PATH,
        json={
            "key": _TEMPLATE_KEY,
            "version": 1,
            "description": "Шаблон для расписания",
            "required_variables": ["debtor_name"],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    response = client.patch(
        TEMPLATE_VERSION_PATH.format(template_key=_TEMPLATE_KEY, version=1),
        json={"status": "active"},
    )
    assert response.status_code == status.HTTP_200_OK


def _create_campaign(client: TestClient) -> str:
    """Создать кампанию и вернуть ее идентификатор."""
    response = client.post(
        CAMPAIGNS_PATH,
        json={
            "name": "Кампания для расписания",
            "channel": "email",
            "template_key": _TEMPLATE_KEY,
            "template_version": 1,
            "selection": {"criteria": {"min_days_overdue": "30"}},
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    return str(response.json()["id"])


def _schedule_payload(run_at: str = _RUN_AT) -> dict[str, object]:
    """Собрать тело запроса планирования."""
    return {
        "schedule": {
            "kind": "one_off",
            "timezone": "Europe/Moscow",
            "run_at": run_at,
        }
    }


def test_schedule_campaign_returns_202(client: TestClient) -> None:
    """Планирование возвращает scheduled-кампанию."""
    _create_active_template(client)
    campaign_id = _create_campaign(client)

    response = client.post(
        CAMPAIGN_SCHEDULE_PATH.format(campaign_id=campaign_id),
        json=_schedule_payload(),
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["schedule"]["kind"] == "one_off"
    assert body["schedule"]["timezone"] == "Europe/Moscow"
    assert body["scheduled_at"] is not None


def test_schedule_campaign_with_past_time_returns_422(client: TestClient) -> None:
    """Время в прошлом отклоняется доменом."""
    _create_active_template(client)
    campaign_id = _create_campaign(client)

    response = client.post(
        CAMPAIGN_SCHEDULE_PATH.format(campaign_id=campaign_id),
        json=_schedule_payload("2020-01-01T00:00:00Z"),
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["type"] == VALIDATION_TYPE


def test_schedule_missing_campaign_returns_404(client: TestClient) -> None:
    """Планирование отсутствующей кампании возвращает 404."""
    response = client.post(
        CAMPAIGN_SCHEDULE_PATH.format(campaign_id=uuid4()),
        json=_schedule_payload(),
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["type"] == NOT_FOUND_TYPE


def test_schedule_twice_returns_409(client: TestClient) -> None:
    """Повторное планирование возвращает 409."""
    _create_active_template(client)
    campaign_id = _create_campaign(client)
    path = CAMPAIGN_SCHEDULE_PATH.format(campaign_id=campaign_id)
    first = client.post(path, json=_schedule_payload())
    assert first.status_code == status.HTTP_202_ACCEPTED

    response = client.post(path, json=_schedule_payload())

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["code"] == CONFLICT_CODE


def test_cancel_scheduled_campaign_returns_202(client: TestClient) -> None:
    """Отмена запланированной кампании возвращает cancelled."""
    _create_active_template(client)
    campaign_id = _create_campaign(client)
    client.post(
        CAMPAIGN_SCHEDULE_PATH.format(campaign_id=campaign_id),
        json=_schedule_payload(),
    )

    response = client.post(CAMPAIGN_CANCEL_PATH.format(campaign_id=campaign_id))

    assert response.status_code == status.HTTP_202_ACCEPTED
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancelled_at"] is not None
    assert body["finished_at"] is not None


def test_cancel_draft_campaign_returns_409(client: TestClient) -> None:
    """Отмена draft-кампании запрещена."""
    _create_active_template(client)
    campaign_id = _create_campaign(client)

    response = client.post(CAMPAIGN_CANCEL_PATH.format(campaign_id=campaign_id))

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["code"] == CONFLICT_CODE


def test_cancel_missing_campaign_returns_404(client: TestClient) -> None:
    """Отмена отсутствующей кампании возвращает 404."""
    response = client.post(CAMPAIGN_CANCEL_PATH.format(campaign_id=uuid4()))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["type"] == NOT_FOUND_TYPE
