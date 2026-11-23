"""Проверка сценариев управления кампаниями до запуска."""

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

from notifications.application.campaigns import (
    CreateCampaignCommand,
    UpdateCampaignCommand,
)
from notifications.application.common import RequestContext
from notifications.application.templates import CreateTemplateCommand
from notifications.domain import (
    EMAIL_CHANNEL,
    AuditAction,
    CampaignId,
    CampaignStatus,
    Channel,
    ConflictError,
    DebtorSelection,
    InvalidStateError,
    NotFoundError,
    TemplateKey,
    ValidationError,
)

_CONTEXT = RequestContext(correlation_id="corr-campaign", trace_id="trace-campaign")


def _selection() -> DebtorSelection:
    """Вернуть критерии выборки для тестов."""
    return DebtorSelection(criteria={"min_days_overdue": "30"})


def _create_command(version: int = 1) -> CreateCampaignCommand:
    """Собрать команду создания кампании."""
    return CreateCampaignCommand(
        name="Напоминание о просрочке",
        channel=EMAIL_CHANNEL,
        template_key=TemplateKey("payment-reminder"),
        template_version=version,
        selection=_selection(),
    )


async def test_create_campaign_persists_and_writes_audit(
    campaign_harness: Any,
) -> None:
    """Создание сохраняет кампанию и audit-событие в одной фиксации."""
    await campaign_harness.create_active_template()
    campaign_harness.audits.clear()

    campaign = await campaign_harness.campaign_service.create_campaign(
        _create_command(),
        _CONTEXT,
    )

    assert campaign.status is CampaignStatus.DRAFT
    assert campaign_harness.factory.units[-1].committed is True
    stored = await campaign_harness.campaigns.get(campaign.id)
    assert stored is not None
    assert stored.name == "Напоминание о просрочке"
    assert len(campaign_harness.audits) == 1
    event = campaign_harness.audits[0]
    assert event.action is AuditAction.CAMPAIGN_CREATED
    assert event.entity_type == "campaign"
    assert event.entity_id == str(campaign.id)
    assert event.campaign_id == campaign.id
    assert event.channel == EMAIL_CHANNEL
    assert event.details["template_key"] == "payment-reminder"
    assert event.details["template_version"] == "1"
    assert event.correlation_id == "corr-campaign"
    assert event.trace_id == "trace-campaign"


async def test_create_campaign_requires_active_template(
    campaign_harness: Any,
) -> None:
    """Шаблон должен существовать и быть активным."""
    campaign_harness.audits.clear()

    with pytest.raises(ConflictError):
        await campaign_harness.campaign_service.create_campaign(
            _create_command(),
            _CONTEXT,
        )

    assert campaign_harness.audits == []


async def test_create_campaign_rejects_draft_template(
    campaign_harness: Any,
) -> None:
    """Черновик шаблона нельзя выбрать для кампании."""
    await campaign_harness.service.create_template(
        _template_command(),
        _CONTEXT,
    )

    with pytest.raises(ConflictError):
        await campaign_harness.campaign_service.create_campaign(
            _create_command(),
            _CONTEXT,
        )


async def test_create_campaign_rejects_invalid_channel(
    campaign_harness: Any,
) -> None:
    """Домен принимает только email."""
    await campaign_harness.create_active_template()
    command = CreateCampaignCommand(
        name="SMS-кампания",
        channel=Channel("sms"),
        template_key=TemplateKey("payment-reminder"),
        template_version=1,
        selection=_selection(),
    )

    with pytest.raises(ValidationError):
        await campaign_harness.campaign_service.create_campaign(command, _CONTEXT)


async def test_get_campaign_returns_stored_value(campaign_harness: Any) -> None:
    """Кампания возвращается по идентификатору."""
    await campaign_harness.create_active_template()
    created = await campaign_harness.campaign_service.create_campaign(
        _create_command(),
        _CONTEXT,
    )

    campaign = await campaign_harness.campaign_service.get_campaign(created.id)

    assert campaign.id == created.id
    assert campaign.name == created.name


async def test_get_missing_campaign_raises_not_found(campaign_harness: Any) -> None:
    """Отсутствующая кампания дает NotFoundError."""
    with pytest.raises(NotFoundError):
        await campaign_harness.campaign_service.get_campaign(CampaignId(uuid4()))


async def test_list_campaigns_filters_and_counts(campaign_harness: Any) -> None:
    """Список возвращает страницу и общее число с фильтром."""
    await campaign_harness.create_active_template()
    first = await campaign_harness.campaign_service.create_campaign(
        _create_command(),
        _CONTEXT,
    )
    await campaign_harness.campaign_service.create_campaign(
        CreateCampaignCommand(
            name="Вторая кампания",
            channel=EMAIL_CHANNEL,
            template_key=TemplateKey("payment-reminder"),
            template_version=1,
            selection=_selection(),
        ),
        _CONTEXT,
    )
    campaign_harness.campaigns.items[first.id].status = CampaignStatus.RUNNING

    drafts = await campaign_harness.campaign_service.list_campaigns(
        status=CampaignStatus.DRAFT,
        limit=10,
        offset=0,
    )
    everything = await campaign_harness.campaign_service.list_campaigns(
        status=None,
        limit=10,
        offset=0,
    )

    assert drafts.total == 1
    assert [campaign.name for campaign in drafts.items] == ["Вторая кампания"]
    assert everything.total == 2


async def test_update_campaign_changes_name_and_writes_audit(
    campaign_harness: Any,
) -> None:
    """Изменение draft-кампании сохраняется и пишет аудит."""
    await campaign_harness.create_active_template()
    created = await campaign_harness.campaign_service.create_campaign(
        _create_command(),
        _CONTEXT,
    )
    campaign_harness.audits.clear()
    later = campaign_harness.clock.now() + timedelta(minutes=5)
    campaign_harness.clock.set(later)

    updated = await campaign_harness.campaign_service.update_campaign(
        created.id,
        UpdateCampaignCommand(
            name="Новое имя",
            template_key=None,
            template_version=None,
            selection=None,
        ),
        _CONTEXT,
    )

    assert updated.name == "Новое имя"
    assert updated.updated_at == later
    assert len(campaign_harness.audits) == 1
    event = campaign_harness.audits[0]
    assert event.action is AuditAction.CAMPAIGN_UPDATED
    assert event.details["changed"] == "name"


async def test_update_campaign_switches_template_version(
    campaign_harness: Any,
) -> None:
    """Кампания может перейти на другую активную версию шаблона."""
    await campaign_harness.create_active_template(version=1)
    created = await campaign_harness.campaign_service.create_campaign(
        _create_command(version=1),
        _CONTEXT,
    )
    await campaign_harness.create_active_template(version=2)
    campaign_harness.audits.clear()

    updated = await campaign_harness.campaign_service.update_campaign(
        created.id,
        UpdateCampaignCommand(
            name=None,
            template_key=TemplateKey("payment-reminder"),
            template_version=2,
            selection=None,
        ),
        _CONTEXT,
    )

    assert updated.template_version == 2
    assert campaign_harness.audits[0].details["template_version"] == "2"


async def test_update_campaign_rejects_archived_template(
    campaign_harness: Any,
) -> None:
    """Неактивная версия шаблона не может быть выбрана."""
    await campaign_harness.create_active_template(version=1)
    created = await campaign_harness.campaign_service.create_campaign(
        _create_command(version=1),
        _CONTEXT,
    )
    await campaign_harness.service.create_template(
        _template_command(version=2),
        _CONTEXT,
    )
    campaign_harness.audits.clear()

    with pytest.raises(ConflictError):
        await campaign_harness.campaign_service.update_campaign(
            created.id,
            UpdateCampaignCommand(
                name=None,
                template_key=TemplateKey("payment-reminder"),
                template_version=2,
                selection=None,
            ),
            _CONTEXT,
        )

    assert campaign_harness.audits == []


async def test_update_campaign_requires_template_pair(
    campaign_harness: Any,
) -> None:
    """Ключ и версия шаблона передаются вместе."""
    await campaign_harness.create_active_template()
    created = await campaign_harness.campaign_service.create_campaign(
        _create_command(),
        _CONTEXT,
    )

    with pytest.raises(ValidationError):
        await campaign_harness.campaign_service.update_campaign(
            created.id,
            UpdateCampaignCommand(
                name=None,
                template_key=TemplateKey("payment-reminder"),
                template_version=None,
                selection=None,
            ),
            _CONTEXT,
        )


async def test_update_campaign_rejects_empty_command(
    campaign_harness: Any,
) -> None:
    """Команда без полей отклоняется."""
    with pytest.raises(ValidationError):
        await campaign_harness.campaign_service.update_campaign(
            CampaignId(uuid4()),
            UpdateCampaignCommand(
                name=None,
                template_key=None,
                template_version=None,
                selection=None,
            ),
            _CONTEXT,
        )


async def test_update_campaign_rejects_non_draft(
    campaign_harness: Any,
) -> None:
    """Кампанию вне draft изменить нельзя."""
    await campaign_harness.create_active_template()
    created = await campaign_harness.campaign_service.create_campaign(
        _create_command(),
        _CONTEXT,
    )
    campaign_harness.campaigns.items[created.id].status = CampaignStatus.RUNNING

    with pytest.raises(InvalidStateError):
        await campaign_harness.campaign_service.update_campaign(
            created.id,
            UpdateCampaignCommand(
                name="Новое имя",
                template_key=None,
                template_version=None,
                selection=None,
            ),
            _CONTEXT,
        )


async def test_update_campaign_without_changes_skips_audit(
    campaign_harness: Any,
) -> None:
    """Повтор текущих значений не пишет аудит."""
    await campaign_harness.create_active_template()
    created = await campaign_harness.campaign_service.create_campaign(
        _create_command(),
        _CONTEXT,
    )
    campaign_harness.audits.clear()

    updated = await campaign_harness.campaign_service.update_campaign(
        created.id,
        UpdateCampaignCommand(
            name=created.name,
            template_key=None,
            template_version=None,
            selection=None,
        ),
        _CONTEXT,
    )

    assert updated.updated_at == created.updated_at
    assert campaign_harness.audits == []


async def test_update_missing_campaign_raises_not_found(
    campaign_harness: Any,
) -> None:
    """Изменение отсутствующей кампании дает NotFoundError."""
    with pytest.raises(NotFoundError):
        await campaign_harness.campaign_service.update_campaign(
            CampaignId(uuid4()),
            UpdateCampaignCommand(
                name="Новое имя",
                template_key=None,
                template_version=None,
                selection=None,
            ),
            _CONTEXT,
        )


def _template_command(version: int = 1) -> CreateTemplateCommand:
    """Собрать команду создания шаблона для тестов кампаний."""
    return CreateTemplateCommand(
        key="payment-reminder",
        version=version,
        description="Шаблон для тестов",
        required_variables=("debtor_name", "amount"),
    )
