"""Проверка API настроек SMTP-адаптера."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from email_channel.adapters.http.constants import CONFIG_PATH, CONFIG_VALIDATE_PATH
from email_channel.adapters.http.problems import (
    NOT_FOUND_CODE,
    NOT_FOUND_TYPE,
    PROBLEM_MEDIA_TYPE,
    VALIDATION_CODE,
    VALIDATION_TYPE,
)
from email_channel.application.config import (
    RequestContext,
    UpdateChannelConfigCommand,
)
from email_channel.config import Settings
from email_channel.domain import (
    EmailAddress,
    NotFoundError,
    SecretRef,
    SmtpConfig,
    ValidationResult,
)
from email_channel.main import create_app

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


class FakeService:
    """Сервис настроек с заданным ответом."""

    def __init__(self, config: SmtpConfig | None = None, error: Exception | None = None) -> None:
        """Сохранить ответ и ошибку."""
        self.config = config
        self.error = error
        self.command: UpdateChannelConfigCommand | None = None
        self.context: RequestContext | None = None

    async def get_config(self) -> SmtpConfig:
        """Вернуть настройки или ошибку."""
        if self.error is not None:
            raise self.error
        if self.config is None:
            raise NotFoundError("Настройки SMTP-адаптера не заданы")
        return self.config

    async def update_config(
        self,
        command: UpdateChannelConfigCommand,
        context: RequestContext,
    ) -> SmtpConfig:
        """Запомнить команду и вернуть настройки."""
        if self.error is not None:
            raise self.error
        self.command = command
        self.context = context
        assert self.config is not None
        return self.config

    async def validate_config(
        self,
        command: UpdateChannelConfigCommand,
    ) -> ValidationResult:
        """Запомнить команду и вернуть успешную проверку."""
        self.command = command
        return ValidationResult(valid=True, errors=(), checked_at=_NOW)


def _config() -> SmtpConfig:
    return SmtpConfig(
        host="smtp.example.com",
        port=587,
        username="user",
        password_ref=SecretRef("SMTP_PASSWORD"),
        from_address=EmailAddress("noreply@example.com"),
        from_name="Bank",
        use_starttls=True,
        timeout_seconds=30.0,
        rate_limit_per_second=10,
        enabled=True,
        updated_at=_NOW,
    )


def _payload() -> dict[str, Any]:
    return {
        "host": "smtp.example.com",
        "port": 587,
        "username": "user",
        "password_ref": "SMTP_PASSWORD",
        "from_address": "noreply@example.com",
        "from_name": "Bank",
        "use_starttls": True,
        "timeout_seconds": 30,
        "rate_limit_per_second": 10,
        "enabled": True,
    }


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Создать тестовый клиент с пустым сервисом."""
    app = create_app(
        Settings(
            service_name="email_channel",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    app.state.channel_config_service = FakeService(None)
    with TestClient(app) as test_client:
        yield test_client


def test_get_config_returns_settings(client: TestClient) -> None:
    """Настройки отдаются в формате контракта."""
    client.app.state.channel_config_service = FakeService(_config())  # type: ignore[attr-defined]

    response = client.get(CONFIG_PATH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["host"] == "smtp.example.com"
    assert payload["port"] == 587
    assert payload["password_ref"] == "SMTP_PASSWORD"
    assert payload["updated_at"].startswith("2026-11-22T12:00:00")


def test_get_config_returns_not_found_problem(client: TestClient) -> None:
    """Ненастроенный канал даёт 404 Problem."""
    response = client.get(CONFIG_PATH)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    payload = response.json()
    assert payload["type"] == NOT_FOUND_TYPE
    assert payload["code"] == NOT_FOUND_CODE


def test_update_config_saves_settings(client: TestClient) -> None:
    """PUT передаёт команду в сервис и возвращает настройки."""
    service = FakeService(_config())
    client.app.state.channel_config_service = service  # type: ignore[attr-defined]

    response = client.put(CONFIG_PATH, json=_payload())

    assert response.status_code == 200
    assert response.json()["host"] == "smtp.example.com"
    assert service.command is not None
    assert service.command.port == 587
    assert service.command.enabled is True
    assert service.context is not None
    assert service.context.correlation_id


def test_validate_config_returns_result(client: TestClient) -> None:
    """POST /v1/config/validate возвращает результат без сохранения."""
    service = FakeService(_config())
    client.app.state.channel_config_service = service  # type: ignore[attr-defined]

    response = client.post(CONFIG_VALIDATE_PATH, json=_payload())

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["errors"] == []
    assert service.command is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"port": 0},
        {"port": 70000},
        {"host": ""},
        {"password_ref": "1bad"},
        {"from_address": "not-email"},
        {"rate_limit_per_second": 0},
        {"timeout_seconds": 0},
        {"unknown": "value"},
    ],
)
def test_update_config_returns_validation_problem(
    client: TestClient,
    overrides: dict[str, Any],
) -> None:
    """Невалидное тело даёт 422 Problem."""
    payload = _payload()
    payload.update(overrides)

    response = client.put(CONFIG_PATH, json=payload)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = response.json()
    assert body["type"] == VALIDATION_TYPE
    assert body["code"] == VALIDATION_CODE
    assert body["instance"] == CONFIG_PATH
