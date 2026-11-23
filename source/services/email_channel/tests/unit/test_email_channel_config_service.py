"""Проверка сценария настройки SMTP-адаптера."""

from datetime import UTC, datetime
from typing import cast

import pytest

from email_channel.application.config import (
    ChannelConfigService,
    RequestContext,
    UpdateChannelConfigCommand,
)
from email_channel.domain import (
    AuditAction,
    AuditActorType,
    AuditEvent,
    EmailAddress,
    NotFoundError,
    SecretRef,
    SmtpConfig,
    ValidationError,
)
from email_channel.ports import UnitOfWorkFactory

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


class FakeClock:
    """Часы с фиксированным временем."""

    def now(self) -> datetime:
        """Вернуть фиксированное время."""
        return _NOW


class FakeConfigRepository:
    """Репозиторий настроек в памяти."""

    def __init__(self, config: SmtpConfig | None = None) -> None:
        """Сохранить начальные настройки."""
        self.config = config
        self.saved: SmtpConfig | None = None

    async def get(self) -> SmtpConfig | None:
        """Вернуть текущие настройки."""
        return self.config

    async def save(self, config: SmtpConfig) -> None:
        """Сохранить настройки."""
        self.saved = config
        self.config = config


class FakeAuditOutbox:
    """Outbox, который запоминает audit-события."""

    def __init__(self) -> None:
        """Создать пустой список."""
        self.events: list[AuditEvent] = []

    async def add(self, event: AuditEvent) -> None:
        """Запомнить событие."""
        self.events.append(event)


class FakeUnitOfWork:
    """Единица работы в памяти."""

    def __init__(self, config_repo: FakeConfigRepository, audit: FakeAuditOutbox) -> None:
        """Сохранить репозиторий и outbox."""
        self.config = config_repo
        self.audit = audit
        self.committed = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        """Открыть единицу работы."""
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Закрыть единицу работы."""
        return None

    async def commit(self) -> None:
        """Зафиксировать изменения."""
        self.committed = True


class FakeUnitOfWorkFactory:
    """Фабрика, которая возвращает одну и ту же единицу работы."""

    def __init__(self, uow: FakeUnitOfWork) -> None:
        """Сохранить единицу работы."""
        self.uow = uow

    def __call__(self) -> FakeUnitOfWork:
        """Вернуть единицу работы."""
        return self.uow


class FakeProbe:
    """Проверка SMTP с заданной ошибкой."""

    def __init__(self, error: str | None = None) -> None:
        """Сохранить описание ошибки."""
        self.error = error

    async def check(self, host: str, port: int, timeout_seconds: float) -> str | None:
        """Вернуть заданную ошибку."""
        return self.error


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


def _command(**overrides: object) -> UpdateChannelConfigCommand:
    values: dict[str, object] = {
        "host": "smtp.example.com",
        "port": 587,
        "username": "user",
        "password_ref": "SMTP_PASSWORD",
        "from_address": "noreply@example.com",
        "from_name": "Bank",
        "use_starttls": True,
        "timeout_seconds": 30.0,
        "rate_limit_per_second": 10,
        "enabled": True,
    }
    values.update(overrides)
    return UpdateChannelConfigCommand(**values)  # type: ignore[arg-type]


def _service(config: SmtpConfig | None = None) -> tuple[ChannelConfigService, FakeUnitOfWork]:
    config_repo = FakeConfigRepository(config)
    audit = FakeAuditOutbox()
    uow = FakeUnitOfWork(config_repo, audit)
    factory = FakeUnitOfWorkFactory(uow)
    service = ChannelConfigService(
        uow_factory=cast(UnitOfWorkFactory, factory),
        clock=FakeClock(),
        probe=FakeProbe(),
    )
    return service, uow


async def test_update_config_saves_settings_and_audit_event() -> None:
    """Настройка сохраняется вместе с channel.config.updated."""
    service, uow = _service()

    config = await service.update_config(
        _command(),
        RequestContext(correlation_id="corr-1", trace_id="trace-1"),
    )

    assert config.host == "smtp.example.com"
    assert config.updated_at == _NOW
    assert uow.config.saved == config
    assert uow.committed is True
    assert len(uow.audit.events) == 1
    event = uow.audit.events[0]
    assert event.action is AuditAction.CHANNEL_CONFIG_UPDATED
    assert event.service == "email_channel"
    assert event.actor.type is AuditActorType.ADMINISTRATOR
    assert event.channel == "email"
    assert event.correlation_id == "corr-1"
    assert event.trace_id == "trace-1"
    details = event.details
    assert details["host"] == "smtp.example.com"
    assert details["port"] == "587"
    assert details["enabled"] == "true"


async def test_get_config_returns_saved_settings() -> None:
    """Сохранённые настройки возвращаются без изменений."""
    config = _config()
    service, _ = _service(config)

    assert await service.get_config() == config


async def test_get_config_raises_not_found() -> None:
    """Ненастроенный канал даёт NotFoundError."""
    service, _ = _service(None)

    with pytest.raises(NotFoundError):
        await service.get_config()


@pytest.mark.parametrize(
    "overrides",
    [
        {"host": ""},
        {"port": 0},
        {"username": ""},
        {"password_ref": ""},
        {"from_address": ""},
        {"from_name": ""},
        {"timeout_seconds": 0},
        {"rate_limit_per_second": 0},
    ],
)
async def test_invalid_command_raises_validation_error(overrides: dict[str, object]) -> None:
    """Некорректные настройки отклоняются до записи."""
    service, uow = _service()

    with pytest.raises(ValidationError):
        await service.update_config(
            _command(**overrides),
            RequestContext(correlation_id="corr-1", trace_id=None),
        )

    assert uow.config.saved is None
    assert uow.audit.events == []
