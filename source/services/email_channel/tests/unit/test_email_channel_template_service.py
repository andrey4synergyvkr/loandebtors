"""Проверка сценария email-шаблонов."""

from datetime import UTC, datetime
from typing import cast

import pytest

from email_channel.application.config import RequestContext
from email_channel.application.templates import (
    EmailTemplateService,
    UpsertEmailTemplateCommand,
)
from email_channel.domain import (
    AuditAction,
    AuditEvent,
    EmailTemplate,
    NotFoundError,
    TemplateKey,
    ValidationError,
)
from email_channel.ports import UnitOfWorkFactory

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


class FakeClock:
    """Часы с фиксированным временем."""

    def now(self) -> datetime:
        """Вернуть фиксированное время."""
        return _NOW


class FakeTemplateRepository:
    """Репозиторий шаблонов в памяти."""

    def __init__(self) -> None:
        """Создать пустое хранилище."""
        self.items: dict[tuple[str, int, str], EmailTemplate] = {}

    async def get(
        self,
        key: TemplateKey,
        version: int,
        locale: str | None = None,
    ) -> EmailTemplate | None:
        """Вернуть шаблон по ключу, версии и локали."""
        if locale is not None:
            return self.items.get((key, version, locale))
        for (item_key, item_version, _), template in self.items.items():
            if item_key == key and item_version == version:
                return template
        return None

    async def list(
        self,
        key: TemplateKey | None = None,
        locale: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[tuple[EmailTemplate, ...], int]:
        """Вернуть страницу шаблонов."""
        items = [
            template
            for (item_key, _, item_locale), template in self.items.items()
            if (key is None or item_key == key) and (locale is None or item_locale == locale)
        ]
        return tuple(items[offset : offset + limit]), len(items)

    async def save(self, template: EmailTemplate) -> None:
        """Сохранить шаблон."""
        self.items[(template.key, template.version, template.locale)] = template


class FakeAuditOutbox:
    """Outbox, который запоминает audit-события."""

    def __init__(self) -> None:
        """Создать пустой список."""
        self.events: list[AuditEvent] = []

    async def add(self, event: AuditEvent) -> None:
        """Запомнить событие."""
        self.events.append(event)


class FakeUnitOfWork:
    """Единица работы с нужными сервису репозиториями."""

    def __init__(self, templates: FakeTemplateRepository, audit: FakeAuditOutbox) -> None:
        """Сохранить репозитории."""
        self.templates = templates
        self.audit = audit
        self.config = None
        self.attempts = None
        self.processed = None
        self.results = None
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


class FakeFactory:
    """Фабрика единицы работы."""

    def __init__(self, uow: FakeUnitOfWork) -> None:
        """Сохранить единицу работы."""
        self.uow = uow

    def __call__(self) -> FakeUnitOfWork:
        """Вернуть единицу работы."""
        return self.uow


def _service() -> tuple[EmailTemplateService, FakeUnitOfWork]:
    templates = FakeTemplateRepository()
    audit = FakeAuditOutbox()
    uow = FakeUnitOfWork(templates, audit)
    service = EmailTemplateService(
        uow_factory=cast(UnitOfWorkFactory, FakeFactory(uow)),
        clock=FakeClock(),
    )
    return service, uow


def _command(**overrides: object) -> UpsertEmailTemplateCommand:
    values: dict[str, object] = {
        "key": "payment-reminder",
        "version": 1,
        "locale": "ru-RU",
        "subject_template": "Тема {{ name }}",
        "html_template": "<p>{{ name }}</p>",
        "plain_text_template": "{{ name }}",
        "required_variables": ("name",),
    }
    values.update(overrides)
    return UpsertEmailTemplateCommand(**values)  # type: ignore[arg-type]


async def test_upsert_template_saves_and_writes_audit() -> None:
    """Шаблон сохраняется вместе с audit-событием."""
    service, uow = _service()

    template = await service.upsert_template(
        _command(),
        RequestContext("corr", "trace"),
    )

    assert template.key == "payment-reminder"
    assert template.updated_at == _NOW
    assert uow.templates.items[("payment-reminder", 1, "ru-RU")] == template
    assert uow.committed is True
    assert len(uow.audit.events) == 1
    event = uow.audit.events[0]
    assert event.action is AuditAction.CHANNEL_CONFIG_UPDATED
    assert event.entity_type == "email_template"
    assert event.entity_id == "payment-reminder:1"
    assert event.details["locale"] == "ru-RU"
    assert event.correlation_id == "corr"
    assert event.trace_id == "trace"


async def test_get_template_returns_saved() -> None:
    """Сохранённый шаблон читается по ключу и версии."""
    service, _ = _service()
    await service.upsert_template(_command(), RequestContext("corr", None))

    template = await service.get_template(TemplateKey("payment-reminder"), 1, "ru-RU")

    assert template.version == 1
    assert template.locale == "ru-RU"


async def test_get_template_raises_not_found() -> None:
    """Отсутствующий шаблон даёт NotFoundError."""
    service, _ = _service()

    with pytest.raises(NotFoundError):
        await service.get_template(TemplateKey("missing"), 1)


async def test_list_templates_returns_page() -> None:
    """Список шаблонов возвращает элементы и общее число."""
    service, _ = _service()
    await service.upsert_template(_command(), RequestContext("corr", None))

    page = await service.list_templates(None, None, 50, 0)

    assert page.total == 1
    assert page.limit == 50
    assert page.offset == 0
    assert page.items[0].key == "payment-reminder"


@pytest.mark.parametrize(
    "overrides",
    [
        {"key": "Bad Key"},
        {"version": 0},
        {"locale": "ru_RU"},
        {"subject_template": ""},
        {"html_template": ""},
        {"plain_text_template": ""},
        {"required_variables": ("name", "name")},
        {"required_variables": ("Bad",)},
    ],
)
async def test_invalid_command_raises_validation_error(
    overrides: dict[str, object],
) -> None:
    """Некорректный шаблон отклоняется до записи."""
    service, uow = _service()

    with pytest.raises(ValidationError):
        await service.upsert_template(
            _command(**overrides),
            RequestContext("corr", None),
        )

    assert uow.templates.items == {}
    assert uow.audit.events == []
