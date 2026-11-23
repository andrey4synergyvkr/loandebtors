"""Проверка жизненного цикла логического шаблона."""

from datetime import UTC, datetime, timedelta

import pytest

from notifications.domain import (
    InvalidStateError,
    NotificationTemplate,
    TemplateKey,
    TemplateStatus,
    ValidationError,
    create_template,
)

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _template(key: str = "payment-reminder", version: int = 1) -> NotificationTemplate:
    """Создать корректную версию шаблона."""
    return create_template(
        key=key,
        version=version,
        description="Напоминание об оплате",
        required_variables=("debtor_name", "amount"),
        now=_NOW,
    )


def test_create_template_validates_and_normalizes_fields() -> None:
    """Создание шаблона проставляет draft и очищает строки."""
    template = create_template(
        key=" payment-reminder ",
        version=2,
        description="  Напоминание об оплате  ",
        required_variables=["debtor_name", "amount"],
        now=_NOW,
    )

    assert template.key == TemplateKey("payment-reminder")
    assert template.version == 2
    assert template.description == "Напоминание об оплате"
    assert template.required_variables == ("debtor_name", "amount")
    assert template.status is TemplateStatus.DRAFT
    assert template.created_at == _NOW
    assert template.updated_at == _NOW


@pytest.mark.parametrize(
    "key",
    ["", "Payment-Reminder", "1reminder", "payment reminder", "a" * 101],
)
def test_create_template_rejects_invalid_key(key: str) -> None:
    """Недопустимый ключ приводит к ValidationError."""
    with pytest.raises(ValidationError):
        _template(key=key)


@pytest.mark.parametrize("version", [0, -1])
def test_create_template_rejects_invalid_version(version: int) -> None:
    """Номер версии должен быть положительным."""
    with pytest.raises(ValidationError):
        _template(version=version)


def test_create_template_rejects_empty_description() -> None:
    """Описание не может состоять из пробелов."""
    with pytest.raises(ValidationError):
        create_template(
            key="payment-reminder",
            version=1,
            description="   ",
            required_variables=(),
            now=_NOW,
        )


@pytest.mark.parametrize(
    "variables",
    [
        ("amount", "amount"),
        ("Amount",),
        ("amount-value",),
        ("",),
    ],
)
def test_create_template_rejects_invalid_variables(variables: tuple[str, ...]) -> None:
    """Переменные должны быть уникальными и в нижнем регистре."""
    with pytest.raises(ValidationError):
        create_template(
            key="payment-reminder",
            version=1,
            description="Напоминание",
            required_variables=variables,
            now=_NOW,
        )


def test_draft_can_be_activated() -> None:
    """Черновик переходит в активный статус и обновляет время."""
    template = _template()
    later = _NOW + timedelta(minutes=5)

    assert template.change_status(TemplateStatus.ACTIVE, later) is True
    assert template.status is TemplateStatus.ACTIVE
    assert template.updated_at == later


def test_draft_can_be_archived_directly() -> None:
    """Черновик можно сразу отправить в архив."""
    template = _template()

    assert template.change_status(TemplateStatus.ARCHIVED, _NOW) is True
    assert template.status is TemplateStatus.ARCHIVED


def test_active_can_be_archived() -> None:
    """Активная версия архивируется."""
    template = _template()
    template.change_status(TemplateStatus.ACTIVE, _NOW)

    assert template.change_status(TemplateStatus.ARCHIVED, _NOW) is True
    assert template.status is TemplateStatus.ARCHIVED


def test_same_status_is_noop() -> None:
    """Повтор текущего статуса не меняет время изменения."""
    template = _template()
    later = _NOW + timedelta(minutes=5)

    assert template.change_status(TemplateStatus.DRAFT, later) is False
    assert template.updated_at == _NOW


def test_active_cannot_return_to_draft() -> None:
    """Активную версию нельзя вернуть в черновик."""
    template = _template()
    template.change_status(TemplateStatus.ACTIVE, _NOW)

    with pytest.raises(InvalidStateError):
        template.change_status(TemplateStatus.DRAFT, _NOW)


def test_archived_is_terminal() -> None:
    """Из архива переходов нет."""
    template = _template()
    template.change_status(TemplateStatus.ARCHIVED, _NOW)

    with pytest.raises(InvalidStateError):
        template.change_status(TemplateStatus.ACTIVE, _NOW)
