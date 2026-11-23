"""Проверка HTTP API запуска кампании."""

from collections.abc import Iterator
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from notifications.adapters.http.constants import (
    CAMPAIGN_PATH,
    CAMPAIGN_SCHEDULE_PATH,
    CAMPAIGN_START_PATH,
    CAMPAIGNS_PATH,
    TEMPLATE_VERSION_PATH,
    TEMPLATES_PATH,
)
from notifications.adapters.http.problems import CONFLICT_CODE, NOT_FOUND_TYPE
from notifications.config import Settings
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


def _create_template(client: TestClient) -> None:
    """Создать и активировать шаблон."""
    response = client.post(
        TEMPLATES_PATH,
        json={
            "key": _TEMPLATE_KEY,
            "version": 1,
            "description": "Шаблон запуска",
            "required_variables": ["debtor_name"],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    client.patch(
        TEMPLATE_VERSION_PATH.format(template_key=_TEMPLATE_KEY, version=1),
        json={"status": "active"},
    )


def _create_campaign(client: TestClient, name: str = "Кампания запуска") -> str:
    """Создать draft-кампанию."""
    response = client.post(
        CAMPAIGNS_PATH,
        json={
            "name": name,
            "channel": "email",
            "template_key": _TEMPLATE_KEY,
            "template_version": 1,
            "selection": {"criteria": {"min_days_overdue": "30"}},
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    return str(response.json()["id"])


def test_start_campaign_returns_running(client: TestClient) -> None:
    """Немедленный запуск возвращает running и ставит событие в outbox."""
    _create_template(client)
    campaign_id = _create_campaign(client)
    harness: Any = cast(Any, client.app).state.test_harness

    response = client.post(CAMPAIGN_START_PATH.format(campaign_id=campaign_id))

    assert response.status_code == status.HTTP_202_ACCEPTED
    body = response.json()
    assert body["status"] == "running"
    assert body["started_at"] is not None
    assert len(harness.start_events) == 1
    assert str(harness.start_events[0].campaign_id) == campaign_id


def test_start_twice_returns_conflict(client: TestClient) -> None:
    """Повторный запуск запрещен."""
    _create_template(client)
    campaign_id = _create_campaign(client)
    path = CAMPAIGN_START_PATH.format(campaign_id=campaign_id)
    first = client.post(path)
    assert first.status_code == status.HTTP_202_ACCEPTED

    response = client.post(path)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["code"] == CONFLICT_CODE


def test_start_scheduled_campaign_returns_conflict(client: TestClient) -> None:
    """Запланированную кампанию запускает Scheduler."""
    _create_template(client)
    campaign_id = _create_campaign(client)
    scheduled = client.post(
        CAMPAIGN_SCHEDULE_PATH.format(campaign_id=campaign_id),
        json={
            "schedule": {
                "kind": "one_off",
                "timezone": "Europe/Moscow",
                "run_at": "2026-12-01T10:00:00Z",
            }
        },
    )
    assert scheduled.status_code == status.HTTP_202_ACCEPTED

    response = client.post(CAMPAIGN_START_PATH.format(campaign_id=campaign_id))

    assert response.status_code == status.HTTP_409_CONFLICT


def test_start_missing_campaign_returns_404(client: TestClient) -> None:
    """Запуск отсутствующей кампании возвращает 404."""
    response = client.post(CAMPAIGN_START_PATH.format(campaign_id=uuid4()))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["type"] == NOT_FOUND_TYPE


def test_start_does_not_change_other_campaign(client: TestClient) -> None:
    """Запуск обновляет только выбранную кампанию."""
    _create_template(client)
    campaign_id = _create_campaign(client)
    other_id = _create_campaign(client, name="Другая кампания")

    client.post(CAMPAIGN_START_PATH.format(campaign_id=campaign_id))

    other = client.get(CAMPAIGN_PATH.format(campaign_id=other_id))
    assert other.json()["status"] == "draft"
