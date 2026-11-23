"""Проверка сценария запуска кампании и создания сообщений."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from notifications.application.campaign_start import (
    CampaignStartService,
    CampaignStartTransientError,
)
from notifications.application.campaigns import CreateCampaignCommand
from notifications.application.common import RequestContext
from notifications.config import Settings
from notifications.domain import (
    EMAIL_CHANNEL,
    AbsDebtor,
    AbsDebtorPage,
    Campaign,
    CampaignId,
    CampaignStart,
    CampaignStatus,
    ContractId,
    DebtorContact,
    DebtorFilter,
    DebtorId,
    DebtorSelection,
    DebtSummary,
    Money,
    TemplateKey,
)
from notifications.ports import AbsPermanentError, AbsTransientError

_CONTEXT = RequestContext(correlation_id="corr-start", trace_id="trace-start")
_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _debtor(debtor_id: str, email: str | None = "debtor@example.test") -> AbsDebtor:
    """Создать должника с контактом или без него."""
    contacts = (
        (DebtorContact(channel=EMAIL_CHANNEL, address=email, is_primary=True),) if email is not None else ()
    )
    return AbsDebtor(
        debtor_id=DebtorId(debtor_id),
        full_name=f"Должник {debtor_id}",
        contacts=contacts,
        debts=(
            DebtSummary(
                contract_id=ContractId(f"CR-{debtor_id}"),
                amount=Money(amount=Decimal("15000.00"), currency="RUB"),
                due_date=date(2025, 1, 15),
                days_overdue=45,
            ),
        ),
    )


class StaticSource:
    """Источник страниц из фиксированного списка должников."""

    def __init__(
        self,
        debtors: tuple[AbsDebtor, ...],
        failure: Exception | None = None,
    ) -> None:
        """Сохранить должников и возможную ошибку."""
        self._debtors = debtors
        self._failure = failure
        self.filters: list[DebtorFilter] = []

    async def fetch_page(
        self,
        page: int,
        page_size: int,
        debtor_filter: DebtorFilter,
    ) -> AbsDebtorPage:
        """Вернуть страницу или ошибку."""
        self.filters.append(debtor_filter)
        if self._failure is not None:
            raise self._failure
        total = len(self._debtors)
        start = (page - 1) * page_size
        end = start + page_size
        items = self._debtors[start:end] if start < total else ()
        return AbsDebtorPage(
            items=items,
            page=page,
            total=total,
            has_next=end < total,
        )


def _service(harness: Any, source: StaticSource) -> CampaignStartService:
    """Собрать сервис запуска на тестовых двойниках."""
    return CampaignStartService(
        source=source,
        uow_factory=harness.factory,
        clock=harness.clock,
        settings=Settings(
            debtor_page_size=10,
            debtor_selection_max_total=100,
            message_max_attempts=2,
            abs_max_attempts=1,
        ),
    )


async def _campaign(harness: Any) -> Campaign:
    """Создать draft-кампанию с активным шаблоном."""
    await harness.create_active_template()
    harness.audits.clear()
    campaign = await harness.campaign_service.create_campaign(
        CreateCampaignCommand(
            name="Кампания запуска",
            channel=EMAIL_CHANNEL,
            template_key=TemplateKey("payment-reminder"),
            template_version=1,
            selection=DebtorSelection(criteria={"min_days_overdue": "30"}),
        ),
        _CONTEXT,
    )
    return cast(Campaign, campaign)


def _event(campaign_id: CampaignId) -> CampaignStart:
    """Собрать событие запуска."""
    return CampaignStart(
        campaign_id=campaign_id,
        scheduled_for=_NOW,
        occurred_at=_NOW,
    )


async def test_start_creates_snapshots_messages_and_outbox(campaign_harness: Any) -> None:
    """Запуск сохраняет снимки, сообщения и команды message.send."""
    campaign = await _campaign(campaign_harness)
    source = StaticSource((_debtor("A-1"), _debtor("A-2", email=None)))
    service = _service(campaign_harness, source)
    campaign_harness.audits.clear()

    await service.handle(_event(campaign.id), _CONTEXT)

    stored = await campaign_harness.campaigns.get(campaign.id)
    assert stored is not None
    assert stored.status is CampaignStatus.RUNNING
    assert stored.selected_debtors == 2
    assert stored.selection_expected == 2
    assert stored.selection_completed_at is not None
    assert stored.messages_created_at is not None
    assert await campaign_harness.snapshots.count(campaign.id) == 2
    messages = list(campaign_harness.messages.items.values())
    assert len(messages) == 1
    assert messages[0].recipient.address == "debtor@example.test"
    assert messages[0].variables["days_overdue"] == "45"
    assert len(campaign_harness.message_commands) == 1
    assert campaign_harness.message_commands[0].message_id == messages[0].id
    assert [event.action.value for event in campaign_harness.audits] == [
        "message.queued",
        "campaign.started",
    ]
    assert source.filters[0].min_days_overdue == 30


async def test_start_is_idempotent(campaign_harness: Any) -> None:
    """Повторная доставка не создает дубли."""
    campaign = await _campaign(campaign_harness)
    service = _service(campaign_harness, StaticSource((_debtor("A-1"),)))
    await service.handle(_event(campaign.id), _CONTEXT)
    snapshots = await campaign_harness.snapshots.count(campaign.id)
    commands = len(campaign_harness.message_commands)

    await service.handle(_event(campaign.id), _CONTEXT)

    assert await campaign_harness.snapshots.count(campaign.id) == snapshots
    assert len(campaign_harness.message_commands) == commands


async def test_permanent_abs_error_marks_campaign_failed(campaign_harness: Any) -> None:
    """Постоянная ошибка АБС переводит кампанию в failed."""
    campaign = await _campaign(campaign_harness)
    service = _service(
        campaign_harness,
        StaticSource((), failure=AbsPermanentError("bad request")),
    )
    campaign_harness.audits.clear()

    await service.handle(_event(campaign.id), _CONTEXT)

    stored = await campaign_harness.campaigns.get(campaign.id)
    assert stored is not None
    assert stored.status is CampaignStatus.FAILED
    assert "bad request" in (stored.failure_reason or "")
    actions = [event.action.value for event in campaign_harness.audits]
    assert actions == ["campaign.failed"]
    assert campaign_harness.message_commands == []


async def test_incomplete_selection_marks_campaign_failed(campaign_harness: Any) -> None:
    """Неполная выборка не сохраняется."""
    campaign = await _campaign(campaign_harness)
    source = StaticSource((_debtor("A-1"),))
    source.fetch_page = _incomplete_page  # type: ignore[method-assign]
    service = _service(campaign_harness, source)

    await service.handle(_event(campaign.id), _CONTEXT)

    stored = await campaign_harness.campaigns.get(campaign.id)
    assert stored is not None
    assert stored.status is CampaignStatus.FAILED
    assert await campaign_harness.snapshots.count(campaign.id) == 0
    assert campaign_harness.message_commands == []


async def test_transient_abs_error_propagates(campaign_harness: Any) -> None:
    """Временная ошибка АБС оставляет кампанию для повтора."""
    campaign = await _campaign(campaign_harness)
    service = _service(
        campaign_harness,
        StaticSource((), failure=AbsTransientError("timeout")),
    )

    with pytest.raises(AbsTransientError):
        await service.handle(_event(campaign.id), _CONTEXT)

    stored = await campaign_harness.campaigns.get(campaign.id)
    assert stored is not None
    assert stored.status is CampaignStatus.DRAFT
    assert stored.messages_created_at is None


async def test_busy_advisory_lock_requests_retry(campaign_harness: Any) -> None:
    """Занятая блокировка кампании приводит к повтору сообщения."""
    campaign = await _campaign(campaign_harness)
    campaign_harness.campaigns.lock_available = False
    service = _service(campaign_harness, StaticSource((_debtor("A-1"),)))

    with pytest.raises(CampaignStartTransientError):
        await service.handle(_event(campaign.id), _CONTEXT)


async def _incomplete_page(
    page: int,
    page_size: int,
    debtor_filter: DebtorFilter,
) -> AbsDebtorPage:
    """Вернуть неполную страницу для проверки защиты."""
    return AbsDebtorPage(
        items=(_debtor("A-1"),),
        page=1,
        total=2,
        has_next=False,
    )
