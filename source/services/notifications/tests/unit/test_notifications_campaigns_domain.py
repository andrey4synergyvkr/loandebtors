"""Проверка жизненного цикла кампании до запуска."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from notifications.domain import (
    EMAIL_CHANNEL,
    Campaign,
    CampaignId,
    CampaignStatus,
    Channel,
    DebtorSelection,
    InvalidStateError,
    TemplateKey,
    ValidationError,
    create_campaign,
)

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
_DEFAULT_KEY = TemplateKey("payment-reminder")
_DEFAULT_SELECTION = DebtorSelection(criteria={"min_days_overdue": "30"})


def _campaign(
    *,
    name: str = "Напоминание о просрочке",
    channel: Channel = EMAIL_CHANNEL,
    template_key: TemplateKey = _DEFAULT_KEY,
    template_version: int = 1,
    selection: DebtorSelection = _DEFAULT_SELECTION,
) -> Campaign:
    """Создать корректную кампанию с возможностью переопределить поля."""
    return create_campaign(
        campaign_id=CampaignId(uuid4()),
        name=name,
        channel=channel,
        template_key=template_key,
        template_version=template_version,
        selection=selection,
        now=_NOW,
    )


def test_create_campaign_sets_draft_state() -> None:
    """Новая кампания создается в draft без выгрузки и расписания."""
    campaign = _campaign()

    assert campaign.status is CampaignStatus.DRAFT
    assert campaign.name == "Напоминание о просрочке"
    assert campaign.channel == EMAIL_CHANNEL
    assert campaign.template_key == TemplateKey("payment-reminder")
    assert campaign.template_version == 1
    assert dict(campaign.selection.criteria) == {"min_days_overdue": "30"}
    assert campaign.schedule is None
    assert campaign.selected_debtors == 0
    assert campaign.selection_expected is None
    assert campaign.selection_completed_at is None
    assert campaign.created_at == _NOW
    assert campaign.updated_at == _NOW


@pytest.mark.parametrize("name", ["", "   ", "a" * 201])
def test_create_campaign_rejects_invalid_name(name: str) -> None:
    """Имя кампании не может быть пустым или слишком длинным."""
    with pytest.raises(ValidationError):
        _campaign(name=name)


def test_create_campaign_rejects_non_email_channel() -> None:
    """В первой версии поддерживается только email."""
    with pytest.raises(ValidationError):
        _campaign(channel=Channel("sms"))


@pytest.mark.parametrize("key", ["", "Payment", "1reminder", "a" * 101])
def test_create_campaign_rejects_invalid_template_key(key: str) -> None:
    """Ключ шаблона проверяется по правилам домена."""
    with pytest.raises(ValidationError):
        _campaign(template_key=TemplateKey(key))


@pytest.mark.parametrize("version", [0, -1])
def test_create_campaign_rejects_invalid_template_version(version: int) -> None:
    """Версия шаблона должна быть положительной."""
    with pytest.raises(ValidationError):
        _campaign(template_version=version)


def test_create_campaign_rejects_invalid_criteria() -> None:
    """Ключи и значения критериев ограничены по длине."""
    with pytest.raises(ValidationError):
        _campaign(selection=DebtorSelection(criteria={"": "30"}))
    with pytest.raises(ValidationError):
        _campaign(selection=DebtorSelection(criteria={"a" * 65: "30"}))
    with pytest.raises(ValidationError):
        _campaign(selection=DebtorSelection(criteria={"min_days_overdue": "1" * 256}))


def test_update_details_changes_fields_in_draft() -> None:
    """Поля кампании меняются в draft и обновляют время."""
    campaign = _campaign()
    later = _NOW + timedelta(minutes=5)

    changed = campaign.update_details(
        name="  Новое имя  ",
        template_key=TemplateKey("payment-reminder"),
        template_version=2,
        selection=DebtorSelection(criteria={"max_days_overdue": "90"}),
        now=later,
    )

    assert set(changed) == {"name", "template_version", "selection"}
    assert campaign.name == "Новое имя"
    assert campaign.template_version == 2
    assert dict(campaign.selection.criteria) == {"max_days_overdue": "90"}
    assert campaign.updated_at == later


def test_update_details_without_changes_keeps_updated_at() -> None:
    """Повтор тех же значений не меняет время."""
    campaign = _campaign()
    later = _NOW + timedelta(minutes=5)

    changed = campaign.update_details(
        name=campaign.name,
        template_key=campaign.template_key,
        template_version=campaign.template_version,
        selection=campaign.selection,
        now=later,
    )

    assert changed == ()
    assert campaign.updated_at == _NOW


def test_update_details_rejects_non_draft_campaign() -> None:
    """Изменять можно только draft-кампанию."""
    campaign = _campaign()
    campaign.status = CampaignStatus.RUNNING

    with pytest.raises(InvalidStateError):
        campaign.update_details(
            name="Новое имя",
            template_key=campaign.template_key,
            template_version=campaign.template_version,
            selection=campaign.selection,
            now=_NOW,
        )
