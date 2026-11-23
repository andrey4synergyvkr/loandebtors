"""Нагрузочный сценарий: кампания на 10 000 должников.

Запуск:
    python source/services/notifications/tests/load/load_10k.py

Требует доступный PostgreSQL из compose на localhost:5432. Скрипт создает
уникальные шаблон и кампанию, выполняет выборку и создание сообщений, печатает
метрики и удаляет созданные данные.
"""

import asyncio
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import asyncpg

from notifications.adapters.persistence.database import Database
from notifications.adapters.persistence.uow import SqlAlchemyUnitOfWorkFactory
from notifications.application.campaign_start import CampaignStartService
from notifications.application.campaigns import CampaignService, CreateCampaignCommand
from notifications.application.common import RequestContext
from notifications.application.templates import CreateTemplateCommand, TemplateService
from notifications.config import Settings
from notifications.domain import (
    EMAIL_CHANNEL,
    AbsDebtor,
    AbsDebtorPage,
    CampaignStart,
    ContractId,
    DebtorContact,
    DebtorFilter,
    DebtorId,
    DebtorSelection,
    DebtSummary,
    Money,
    TemplateKey,
    TemplateStatus,
)
from notifications.infrastructure.clock import SystemClock

TOTAL = 10_000
PAGE_SIZE = 500
CONTEXT = RequestContext(correlation_id="load-10k", trace_id=None)


class StaticSource:
    """Источник страниц из памяти."""

    def __init__(self, debtors: tuple[AbsDebtor, ...]) -> None:
        """Сохранить должников."""
        self._debtors = debtors

    async def fetch_page(
        self,
        page: int,
        page_size: int,
        debtor_filter: DebtorFilter,
    ) -> AbsDebtorPage:
        """Вернуть страницу."""
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


def _debtors() -> tuple[AbsDebtor, ...]:
    """Создать 10 000 детерминированных должников."""
    return tuple(
        AbsDebtor(
            debtor_id=DebtorId(f"LOAD-{index:06d}"),
            full_name=f"Нагрузочный Должник {index:06d}",
            contacts=(
                DebtorContact(
                    channel=EMAIL_CHANNEL,
                    address=f"load{index:06d}@example.test",
                    is_primary=True,
                ),
            ),
            debts=(
                DebtSummary(
                    contract_id=ContractId(f"LOAD-CR-{index:06d}"),
                    amount=Money(amount=Decimal("1000.00"), currency="RUB"),
                    due_date=date(2025, 1, 15),
                    days_overdue=30,
                ),
            ),
        )
        for index in range(1, TOTAL + 1)
    )


async def _counts(campaign_id: UUID) -> dict[str, int]:
    """Вернуть счетчики созданных записей."""
    conn = await asyncpg.connect("postgresql://loandebtors:loandebtors@localhost:5432/loandebtors")
    try:
        row = await conn.fetchrow(
            "SELECT "
            "(SELECT count(*) FROM notification.debtor_snapshots WHERE campaign_id=$1) AS snapshots, "
            "(SELECT count(*) FROM notification.messages WHERE campaign_id=$1) AS messages, "
            "(SELECT count(*) FROM notification.outbox WHERE payload->>'campaign_id'=$2) AS outbox",
            campaign_id,
            str(campaign_id),
        )
        return {key: int(value) for key, value in dict(row).items()}
    finally:
        await conn.close()


async def _cleanup(campaign_id: UUID, template_key: str) -> None:
    """Удалить созданные нагрузочные данные."""
    conn = await asyncpg.connect("postgresql://loandebtors:loandebtors@localhost:5432/loandebtors")
    try:
        await conn.execute(
            "DELETE FROM notification.outbox WHERE payload->>'campaign_id'=$1",
            str(campaign_id),
        )
        await conn.execute(
            "DELETE FROM notification.campaigns WHERE id=$1",
            campaign_id,
        )
        await conn.execute(
            "DELETE FROM notification.templates WHERE key=$1",
            template_key,
        )
    finally:
        await conn.close()


async def main() -> None:
    """Выполнить нагрузочный сценарий."""
    settings = Settings(
        database_url="postgresql+asyncpg://loandebtors:loandebtors@localhost:5432/loandebtors",
        debtor_page_size=PAGE_SIZE,
        debtor_selection_max_total=TOTAL,
        message_max_attempts=3,
    )
    database = Database(settings)
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    clock = SystemClock()
    templates = TemplateService(uow_factory=uow_factory, clock=clock)
    campaigns = CampaignService(uow_factory=uow_factory, clock=clock)
    key = f"load-{uuid4().hex[:8]}"
    campaign_id: UUID | None = None
    try:
        template = await templates.create_template(
            CreateTemplateCommand(
                key=key,
                version=1,
                description="Нагрузочный шаблон",
                required_variables=("debtor_name", "amount"),
            ),
            CONTEXT,
        )
        await templates.update_status(
            template.key,
            template.version,
            TemplateStatus.ACTIVE,
            CONTEXT,
        )
        campaign = await campaigns.create_campaign(
            CreateCampaignCommand(
                name="Нагрузочная кампания 10000",
                channel=EMAIL_CHANNEL,
                template_key=TemplateKey(key),
                template_version=1,
                selection=DebtorSelection(criteria={"min_days_overdue": "30"}),
            ),
            CONTEXT,
        )
        campaign_id = campaign.id
        debtors = _debtors()
        service = CampaignStartService(
            source=StaticSource(debtors),
            uow_factory=uow_factory,
            clock=clock,
            settings=settings,
        )
        started = time.perf_counter()
        await service.handle(
            CampaignStart(
                campaign_id=campaign.id,
                scheduled_for=datetime.now(UTC),
                occurred_at=datetime.now(UTC),
            ),
            CONTEXT,
        )
        elapsed = time.perf_counter() - started
        counts = await _counts(campaign.id)
        print(f"LOAD10K seconds={elapsed:.2f}")
        print(f"LOAD10K snapshots={counts['snapshots']}")
        print(f"LOAD10K messages={counts['messages']}")
        print(f"LOAD10K outbox={counts['outbox']}")
        if counts["snapshots"] != TOTAL or counts["messages"] != TOTAL:
            raise SystemExit("Нагрузочный сценарий вернул неверное число записей")
    finally:
        if campaign_id is not None:
            await _cleanup(campaign_id, key)
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
