"""Проверка HTTP API сообщений кампании."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from notifications.adapters.http.constants import (
    CAMPAIGN_MESSAGE_PATH,
    CAMPAIGN_MESSAGES_PATH,
    CAMPAIGNS_PATH,
    TEMPLATE_VERSION_PATH,
    TEMPLATES_PATH,
)
from notifications.adapters.http.problems import NOT_FOUND_TYPE, VALIDATION_TYPE
from notifications.config import Settings
from notifications.domain import (
    EMAIL_CHANNEL,
    CampaignId,
    DebtorId,
    IdempotencyKey,
    MessageId,
    MessageStatus,
    NotificationMessage,
    Recipient,
    TemplateKey,
)
from notifications.main import create_app

_TEMPLATE_KEY = "payment-reminder"
_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


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
            "description": "Шаблон сообщений",
            "required_variables": ["debtor_name"],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    client.patch(
        TEMPLATE_VERSION_PATH.format(template_key=_TEMPLATE_KEY, version=1),
        json={"status": "active"},
    )


def _create_campaign(client: TestClient, name: str = "Кампания сообщений") -> str:
    """Создать кампанию через API."""
    response = client.post(
        CAMPAIGNS_PATH,
        json={
            "name": name,
            "channel": "email",
            "template_key": _TEMPLATE_KEY,
            "template_version": 1,
            "selection": {"criteria": {}},
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    return str(response.json()["id"])


def _message(campaign_id: str, status: MessageStatus) -> NotificationMessage:
    """Создать сообщение для тестового репозитория."""
    return NotificationMessage(
        id=MessageId(uuid4()),
        campaign_id=CampaignId(UUID(campaign_id)),
        debtor_id=DebtorId(f"ABS-{uuid4().hex[:6]}"),
        channel=EMAIL_CHANNEL,
        template_key=TemplateKey(_TEMPLATE_KEY),
        template_version=1,
        variables={"debtor_name": "Иван"},
        recipient=Recipient(channel=EMAIL_CHANNEL, address="debtor@example.test"),
        idempotency_key=IdempotencyKey(str(uuid4())),
        status=status,
        attempt_count=0,
        max_attempts=3,
        created_at=_NOW,
        queued_at=_NOW,
        last_attempt_at=None,
        sent_at=None,
        failed_at=None,
        next_attempt_at=None,
        last_error_code=None,
        last_error_message=None,
    )


def _seed_messages(client: TestClient, campaign_id: str) -> list[NotificationMessage]:
    """Добавить сообщения в тестовый репозиторий."""
    harness: Any = cast(Any, client.app).state.test_harness
    messages = [
        _message(campaign_id, MessageStatus.QUEUED),
        _message(campaign_id, MessageStatus.SENT),
    ]
    for message in messages:
        harness.messages.items[message.id] = message
    return messages


def test_list_messages_returns_page(client: TestClient) -> None:
    """Список сообщений возвращает страницу и total."""
    _create_template(client)
    campaign_id = _create_campaign(client)
    _seed_messages(client, campaign_id)

    response = client.get(CAMPAIGN_MESSAGES_PATH.format(campaign_id=campaign_id))

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_messages_filters_by_status(client: TestClient) -> None:
    """Фильтр по статусу применяется к странице и total."""
    _create_template(client)
    campaign_id = _create_campaign(client)
    _seed_messages(client, campaign_id)

    response = client.get(
        CAMPAIGN_MESSAGES_PATH.format(campaign_id=campaign_id),
        params={"status": "queued"},
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "queued"


def test_list_messages_for_missing_campaign_returns_404(client: TestClient) -> None:
    """Список сообщений отсутствующей кампании возвращает 404."""
    response = client.get(CAMPAIGN_MESSAGES_PATH.format(campaign_id=uuid4()))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["type"] == NOT_FOUND_TYPE


def test_get_message_returns_details(client: TestClient) -> None:
    """Сообщение возвращается по идентификатору."""
    _create_template(client)
    campaign_id = _create_campaign(client)
    message = _seed_messages(client, campaign_id)[0]

    response = client.get(CAMPAIGN_MESSAGE_PATH.format(campaign_id=campaign_id, message_id=message.id))

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["id"] == str(message.id)
    assert body["campaign_id"] == campaign_id
    assert body["recipient"]["address"] == "debtor@example.test"


def test_get_message_from_other_campaign_returns_404(client: TestClient) -> None:
    """Сообщение проверяется на принадлежность кампании."""
    _create_template(client)
    first = _create_campaign(client)
    second = _create_campaign(client)
    message = _seed_messages(client, first)[0]

    response = client.get(CAMPAIGN_MESSAGE_PATH.format(campaign_id=second, message_id=message.id))

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_list_messages_validates_limit(client: TestClient) -> None:
    """Недопустимый limit возвращает 422."""
    _create_template(client)
    campaign_id = _create_campaign(client)

    response = client.get(
        CAMPAIGN_MESSAGES_PATH.format(campaign_id=campaign_id),
        params={"limit": 0},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["type"] == VALIDATION_TYPE
