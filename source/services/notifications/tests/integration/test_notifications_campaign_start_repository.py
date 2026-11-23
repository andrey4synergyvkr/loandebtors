"""Интеграционная проверка запуска кампании и выборки."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import suppress
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from notifications.adapters.persistence.models import (
    CampaignRow,
    DebtorSnapshotRow,
    MessageRow,
    OutboxRow,
)
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
    Campaign,
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
    TemplateStatus,
)
from notifications.infrastructure.clock import SystemClock

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[5]
_POSTGRES_IMAGE = "postgres:16-alpine"
_CONTEXT = RequestContext(correlation_id="integration-start", trace_id=None)


def _apply_migrations(database_url: str) -> None:
    """Применить миграции Notifications к тестовой базе."""
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "source/services/notifications/alembic.ini",
            "upgrade",
            "head",
        ],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"Миграции не применились: {result.stdout}\n{result.stderr}")


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    """Поднять PostgreSQL и применить миграции."""
    postgres: PostgresContainer | None = None
    try:
        postgres = PostgresContainer(_POSTGRES_IMAGE)
        postgres.start()
    except Exception as exc:
        if postgres is not None:
            with suppress(Exception):
                postgres.stop()
        pytest.skip(f"Docker или PostgreSQL недоступны: {exc}")

    assert postgres is not None
    url = postgres.get_connection_url().replace(
        "postgresql+psycopg2",
        "postgresql+asyncpg",
    )
    try:
        _apply_migrations(url)
        yield url
    finally:
        with suppress(Exception):
            postgres.stop()


@pytest.fixture
async def session_factory(
    database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Создать фабрику сессий к тестовой базе."""
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


class StaticSource:
    """Источник страниц из фиксированного списка должников."""

    def __init__(self, debtors: Sequence[AbsDebtor]) -> None:
        """Сохранить должников."""
        self._debtors = tuple(debtors)

    async def fetch_page(
        self,
        page: int,
        page_size: int,
        debtor_filter: DebtorFilter,
    ) -> AbsDebtorPage:
        """Вернуть страницу выборки."""
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


def _debtor(debtor_id: str, email: str | None = "debtor@example.test") -> AbsDebtor:
    """Создать должника для выборки."""
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
                amount=Money(amount=Decimal("1000.00"), currency="RUB"),
                due_date=date(2025, 1, 15),
                days_overdue=30,
            ),
        ),
    )


async def _draft_campaign(
    session_factory: async_sessionmaker[AsyncSession],
    key: str,
) -> Campaign:
    """Создать активный шаблон и draft-кампанию."""
    uow_factory = SqlAlchemyUnitOfWorkFactory(session_factory)
    clock = SystemClock()
    templates = TemplateService(uow_factory=uow_factory, clock=clock)
    template = await templates.create_template(
        CreateTemplateCommand(
            key=key,
            version=1,
            description="Шаблон интеграционного запуска",
            required_variables=("debtor_name", "amount"),
        ),
        _CONTEXT,
    )
    await templates.update_status(template.key, template.version, TemplateStatus.ACTIVE, _CONTEXT)
    campaigns = CampaignService(uow_factory=uow_factory, clock=clock)
    return await campaigns.create_campaign(
        CreateCampaignCommand(
            name="Интеграционная кампания запуска",
            channel=EMAIL_CHANNEL,
            template_key=TemplateKey(key),
            template_version=1,
            selection=DebtorSelection(criteria={"min_days_overdue": "30"}),
        ),
        _CONTEXT,
    )


async def test_start_creates_snapshots_messages_and_outbox(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Запуск сохраняет снимки, сообщения и команды message.send."""
    campaign = await _draft_campaign(session_factory, "integration-start-full")
    uow_factory = SqlAlchemyUnitOfWorkFactory(session_factory)
    service = CampaignStartService(
        source=StaticSource((_debtor("A-1"), _debtor("A-2", email=None))),
        uow_factory=uow_factory,
        clock=SystemClock(),
        settings=Settings(debtor_page_size=10, debtor_selection_max_total=100),
    )

    await service.handle(
        CampaignStart(
            campaign_id=campaign.id,
            scheduled_for=datetime.now(UTC),
            occurred_at=datetime.now(UTC),
        ),
        _CONTEXT,
    )

    async with session_factory() as session:
        snapshots = await session.scalar(
            select(func.count())
            .select_from(DebtorSnapshotRow)
            .where(DebtorSnapshotRow.campaign_id == campaign.id)
        )
        messages = (
            await session.scalars(select(MessageRow).where(MessageRow.campaign_id == campaign.id))
        ).all()
        outbox = (
            await session.scalars(select(OutboxRow).where(OutboxRow.event_type == "message.send"))
        ).all()
        campaign_row = await session.get(CampaignRow, campaign.id)

    assert campaign_row is not None
    assert campaign_row.status == "running"
    assert campaign_row.messages_created_at is not None
    assert snapshots == 2
    assert len(messages) == 1
    assert messages[0].recipient["address"] == "debtor@example.test"
    assert len(outbox) == 1
    assert outbox[0].payload["message_id"] == str(messages[0].id)
    assert outbox[0].routing_key == "message.send"
    assert outbox[0].exchange == "loan-debtors.events"


async def test_message_sent_completes_campaign(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """message.sent закрывает сообщение, пишет попытку и завершает кампанию."""
    from notifications.adapters.persistence.models import MessageAttemptRow, MessageRow
    from notifications.application.message_results import MessageResultService
    from notifications.domain import (
        IdempotencyKey,
        MessageId,
        MessageSent,
        MessageStatus,
        NotificationMessage,
        Recipient,
    )

    campaign = await _draft_campaign(session_factory, "integration-results-sent")
    uow_factory = SqlAlchemyUnitOfWorkFactory(session_factory)
    message = NotificationMessage(
        id=MessageId(uuid4()),
        campaign_id=campaign.id,
        debtor_id=DebtorId("A-1"),
        channel=EMAIL_CHANNEL,
        template_key=TemplateKey("integration-results-sent"),
        template_version=1,
        variables={"debtor_name": "Иван"},
        recipient=Recipient(channel=EMAIL_CHANNEL, address="debtor@example.test"),
        idempotency_key=IdempotencyKey(str(uuid4())),
        status=MessageStatus.QUEUED,
        attempt_count=0,
        max_attempts=3,
        created_at=datetime.now(UTC),
        queued_at=datetime.now(UTC),
        last_attempt_at=None,
        sent_at=None,
        failed_at=None,
        next_attempt_at=None,
        last_error_code=None,
        last_error_message=None,
    )
    async with uow_factory() as uow:
        stored_campaign = await uow.campaigns.get(campaign.id)
        assert stored_campaign is not None
        stored_campaign.mark_running(datetime.now(UTC))
        stored_campaign.mark_messages_created(datetime.now(UTC))
        await uow.campaigns.save(stored_campaign)
        await uow.messages.add_many([message])
        await uow.commit()

    service = MessageResultService(
        uow_factory=uow_factory,
        clock=SystemClock(),
        settings=Settings(),
    )
    await service.handle_sent(
        MessageSent(
            message_id=message.id,
            campaign_id=campaign.id,
            channel=EMAIL_CHANNEL,
            attempt_number=1,
            provider_message_id="smtp-1",
            occurred_at=datetime.now(UTC),
        ),
        _CONTEXT,
    )

    async with session_factory() as session:
        message_row = await session.get(MessageRow, message.id)
        campaign_row = await session.get(CampaignRow, campaign.id)
        attempts = await session.scalar(
            select(func.count())
            .select_from(MessageAttemptRow)
            .where(MessageAttemptRow.message_id == message.id)
        )

    assert message_row is not None
    assert message_row.status == MessageStatus.SENT.value
    assert campaign_row is not None
    assert campaign_row.status == CampaignStatus.COMPLETED.value
    assert attempts == 1


async def test_transient_failure_schedules_outbox_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Временная ошибка пишет message.send с будущим available_at."""
    from notifications.adapters.persistence.models import MessageRow
    from notifications.application.message_results import MessageResultService
    from notifications.domain import (
        DeliveryOutcome,
        IdempotencyKey,
        MessageFailed,
        MessageId,
        MessageStatus,
        NotificationMessage,
        Recipient,
    )

    campaign = await _draft_campaign(session_factory, "integration-results-retry")
    uow_factory = SqlAlchemyUnitOfWorkFactory(session_factory)
    message = NotificationMessage(
        id=MessageId(uuid4()),
        campaign_id=campaign.id,
        debtor_id=DebtorId("A-2"),
        channel=EMAIL_CHANNEL,
        template_key=TemplateKey("integration-results-retry"),
        template_version=1,
        variables={},
        recipient=Recipient(channel=EMAIL_CHANNEL, address="debtor@example.test"),
        idempotency_key=IdempotencyKey(str(uuid4())),
        status=MessageStatus.QUEUED,
        attempt_count=0,
        max_attempts=3,
        created_at=datetime.now(UTC),
        queued_at=datetime.now(UTC),
        last_attempt_at=None,
        sent_at=None,
        failed_at=None,
        next_attempt_at=None,
        last_error_code=None,
        last_error_message=None,
    )
    async with uow_factory() as uow:
        stored_campaign = await uow.campaigns.get(campaign.id)
        assert stored_campaign is not None
        stored_campaign.mark_running(datetime.now(UTC))
        stored_campaign.mark_messages_created(datetime.now(UTC))
        await uow.campaigns.save(stored_campaign)
        await uow.messages.add_many([message])
        await uow.commit()

    service = MessageResultService(
        uow_factory=uow_factory,
        clock=SystemClock(),
        settings=Settings(
            message_retry_base_seconds=10.0,
            message_retry_max_seconds=60.0,
        ),
    )
    await service.handle_failed(
        MessageFailed(
            message_id=message.id,
            campaign_id=campaign.id,
            channel=EMAIL_CHANNEL,
            attempt_number=1,
            outcome=DeliveryOutcome.TRANSIENT_FAILURE,
            retryable=True,
            error_code="SMTP_TIMEOUT",
            error_message="timeout",
            occurred_at=datetime.now(UTC),
        ),
        _CONTEXT,
    )

    async with session_factory() as session:
        message_row = await session.get(MessageRow, message.id)
        retry_row = (
            await session.scalars(
                select(OutboxRow).where(
                    OutboxRow.event_type == "message.send",
                    OutboxRow.payload["message_id"].astext == str(message.id),
                )
            )
        ).first()

    assert message_row is not None
    assert message_row.status == MessageStatus.QUEUED.value
    assert message_row.next_attempt_at is not None
    assert retry_row is not None
    assert retry_row.available_at == message_row.next_attempt_at
    assert retry_row.published_at is None


async def test_exhausted_outbox_is_closed_by_maintenance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Обслуживание закрывает message.send после предела попыток outbox."""
    from sqlalchemy import update

    from notifications.application.maintenance import MaintenanceService

    campaign = await _draft_campaign(session_factory, "integration-outbox-exhausted")
    uow_factory = SqlAlchemyUnitOfWorkFactory(session_factory)
    settings = Settings(
        debtor_page_size=10,
        debtor_selection_max_total=100,
        outbox_max_attempts=2,
    )
    start = CampaignStartService(
        source=StaticSource((_debtor("A-OUTBOX"),)),
        uow_factory=uow_factory,
        clock=SystemClock(),
        settings=settings,
    )
    await start.handle(
        CampaignStart(
            campaign_id=campaign.id,
            scheduled_for=datetime.now(UTC),
            occurred_at=datetime.now(UTC),
        ),
        _CONTEXT,
    )

    async with session_factory() as session:
        command = (
            await session.scalars(
                select(OutboxRow).where(
                    OutboxRow.event_type == "message.send",
                    OutboxRow.payload["campaign_id"].astext == str(campaign.id),
                )
            )
        ).one()
        message_id = command.payload["message_id"]
        await session.execute(
            update(OutboxRow)
            .where(OutboxRow.id == command.id)
            .values(attempts=settings.outbox_max_attempts, available_at=datetime.now(UTC))
        )
        await session.commit()

    service = MaintenanceService(
        uow_factory=uow_factory,
        clock=SystemClock(),
        retention_days=settings.retention_days,
        recovery_grace_seconds=settings.recovery_grace_seconds,
        batch_size=settings.maintenance_batch_size,
        outbox_max_attempts=settings.outbox_max_attempts,
    )
    result = await service.run_once()

    async with session_factory() as session:
        message_row = await session.get(MessageRow, message_id)
        command_row = await session.get(OutboxRow, command.id)
        campaign_row = await session.get(CampaignRow, campaign.id)

    assert result.exhausted_messages == 1
    assert message_row is not None
    assert message_row.status == "failed"
    assert message_row.last_error_code == "outbox_publish_exhausted"
    assert command_row is not None
    assert command_row.published_at is None
    assert command_row.failed_at is not None
    assert campaign_row is not None
    assert campaign_row.status == CampaignStatus.COMPLETED.value
