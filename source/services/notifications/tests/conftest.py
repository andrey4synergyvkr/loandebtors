"""Общие тестовые двойники Notifications."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

import pytest

from notifications.application.campaigns import CampaignService
from notifications.application.common import RequestContext
from notifications.application.templates import CreateTemplateCommand, TemplateService
from notifications.domain import (
    EMAIL_CHANNEL,
    AbsDebtor,
    AbsDebtorPage,
    AuditEvent,
    Campaign,
    CampaignCancelled,
    CampaignId,
    CampaignScheduled,
    CampaignStart,
    CampaignStatus,
    ContractId,
    DebtorContact,
    DebtorFilter,
    DebtorId,
    DebtorSnapshot,
    DebtSummary,
    MessageAttempt,
    MessageId,
    MessageStatus,
    Money,
    NotFoundError,
    NotificationCommand,
    NotificationMessage,
    NotificationTemplate,
    TemplateKey,
    TemplateStatus,
)
from notifications.ports import (
    AbsDebtorSource,
    AbsPermanentError,
    AbsTransientError,
    AuditEventOutbox,
    CampaignEventOutbox,
    CampaignRepository,
    DebtorSnapshotRepository,
    ExhaustedMessageCommand,
    MaintenanceStore,
    MessageAttemptRepository,
    MessageCommandOutbox,
    NotificationMessageRepository,
    NotificationTemplateRepository,
    UnitOfWork,
)

FailureMode = Literal["unavailable", "incomplete", "permanent"]


def _matches_filter(debtor: AbsDebtor, debtor_filter: DebtorFilter) -> bool:
    """Проверить, попадает ли должник в выборку по критериям."""
    days = [debt.days_overdue for debt in debtor.debts]
    if debtor_filter.min_days_overdue is not None and not any(
        day >= debtor_filter.min_days_overdue for day in days
    ):
        return False
    if debtor_filter.max_days_overdue is not None and not any(
        day <= debtor_filter.max_days_overdue for day in days
    ):
        return False
    return debtor_filter.channel is None or any(
        contact.channel == debtor_filter.channel for contact in debtor.contacts
    )


def _default_debtors() -> tuple[AbsDebtor, ...]:
    """Создать пять детерминированных должников для тестов."""
    return tuple(
        AbsDebtor(
            debtor_id=DebtorId(f"ABS-{index:06d}"),
            full_name=f"Тестовый Должник {index:02d}",
            contacts=(
                DebtorContact(
                    channel=EMAIL_CHANNEL,
                    address=f"debtor{index:02d}@example.test",
                    is_primary=True,
                ),
            ),
            debts=(
                DebtSummary(
                    contract_id=ContractId(f"CR-2024-{index:04d}"),
                    amount=Money(amount=Decimal("1000.00") * index, currency="RUB"),
                    due_date=date(2025, 1, 15),
                    days_overdue=30 * index,
                ),
            ),
        )
        for index in range(1, 6)
    )


class FakeAbsDebtorSource:
    """Тестовый источник страниц АБС."""

    def __init__(
        self,
        debtors: tuple[AbsDebtor, ...] | None = None,
        failure: FailureMode | None = None,
    ) -> None:
        """Сохранить должников и режим сбоя."""
        self._debtors = debtors or _default_debtors()
        self._failure = failure

    async def fetch_page(
        self,
        page: int,
        page_size: int,
        debtor_filter: DebtorFilter,
    ) -> AbsDebtorPage:
        """Вернуть страницу выборки или смоделировать сбой."""
        if page < 1:
            raise ValueError("Номер страницы должен быть не меньше 1")
        if page_size < 1:
            raise ValueError("Размер страницы должен быть не меньше 1")
        if self._failure == "unavailable":
            raise AbsTransientError("АБС недоступна")
        if self._failure == "permanent":
            raise AbsPermanentError("АБС отклонила запрос")

        debtors = tuple(debtor for debtor in self._debtors if _matches_filter(debtor, debtor_filter))
        total = len(debtors)
        start = (page - 1) * page_size
        end = start + page_size
        items = debtors[start:end] if start < total else ()
        has_next = end < total
        if self._failure == "incomplete" and items:
            items = items[:-1]
            has_next = False
        return AbsDebtorPage(items=items, page=page, total=total, has_next=has_next)


class FixedClock:
    """Часы с фиксированным временем для детерминированных тестов."""

    def __init__(self, now: datetime) -> None:
        """Сохранить текущее время."""
        self._now = now

    def now(self) -> datetime:
        """Вернуть зафиксированное время."""
        return self._now

    def set(self, now: datetime) -> None:
        """Изменить зафиксированное время."""
        self._now = now


class FakeTemplateRepository:
    """Репозиторий шаблонов в памяти."""

    def __init__(self) -> None:
        """Создать пустое хранилище."""
        self.items: dict[tuple[str, int], NotificationTemplate] = {}

    async def get(
        self,
        key: TemplateKey,
        version: int | None = None,
    ) -> NotificationTemplate | None:
        """Вернуть версию шаблона или последнюю активную."""
        if version is not None:
            stored = self.items.get((key, version))
            return None if stored is None else replace(stored)
        active = [
            template
            for template in self.items.values()
            if template.key == key and template.status is TemplateStatus.ACTIVE
        ]
        if not active:
            return None
        return replace(max(active, key=lambda template: template.version))

    async def save(self, template: NotificationTemplate) -> None:
        """Сохранить копию версии шаблона."""
        self.items[(template.key, template.version)] = replace(template)

    async def list(
        self,
        status: TemplateStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NotificationTemplate]:
        """Вернуть страницу версий шаблонов."""
        templates = [
            replace(template)
            for template in self.items.values()
            if status is None or template.status is status
        ]
        templates.sort(key=lambda template: (template.key, -template.version))
        return templates[offset : offset + limit]

    async def count(self, status: TemplateStatus | None = None) -> int:
        """Вернуть число версий с учётом фильтра."""
        return sum(1 for template in self.items.values() if status is None or template.status is status)

    async def archive_active(
        self,
        key: TemplateKey,
        except_version: int,
        now: datetime,
    ) -> None:
        """Перевести другие активные версии ключа в архив."""
        for identity, template in list(self.items.items()):
            if (
                template.key == key
                and template.version != except_version
                and template.status is TemplateStatus.ACTIVE
            ):
                self.items[identity] = replace(
                    template,
                    status=TemplateStatus.ARCHIVED,
                    updated_at=now,
                )


class FakeAuditOutbox:
    """Собирает audit-события текущей единицы работы."""

    def __init__(self, sink: list[AuditEvent]) -> None:
        """Сохранить список для записи событий."""
        self._sink = sink

    async def add(self, event: AuditEvent) -> None:
        """Добавить событие в список."""
        self._sink.append(event)


class FakeCampaignRepository:
    """Репозиторий кампаний в памяти."""

    def __init__(self) -> None:
        """Создать пустое хранилище."""
        self.items: dict[UUID, Campaign] = {}
        self.lock_available = True

    async def add(self, campaign: Campaign) -> None:
        """Сохранить новую кампанию."""
        self.items[campaign.id] = replace(campaign)

    async def get(self, campaign_id: CampaignId) -> Campaign | None:
        """Вернуть кампанию или None."""
        stored = self.items.get(campaign_id)
        return None if stored is None else replace(stored)

    async def save(self, campaign: Campaign) -> None:
        """Сохранить изменения существующей кампании."""
        if campaign.id not in self.items:
            raise NotFoundError(f"Кампания {campaign.id} не найдена")
        self.items[campaign.id] = replace(campaign)

    async def list(
        self,
        status: CampaignStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Campaign]:
        """Вернуть страницу кампаний."""
        campaigns = [
            replace(campaign)
            for campaign in self.items.values()
            if status is None or campaign.status is status
        ]
        campaigns.sort(key=lambda campaign: (campaign.created_at, str(campaign.id)), reverse=True)
        return campaigns[offset : offset + limit]

    async def count(self, status: CampaignStatus | None = None) -> int:
        """Вернуть число кампаний с учётом фильтра."""
        return sum(1 for campaign in self.items.values() if status is None or campaign.status is status)

    async def try_advisory_lock(self, campaign_id: CampaignId) -> bool:
        """Вернуть настроенный результат захвата блокировки."""
        return self.lock_available

    async def complete_if_running(self, campaign_id: CampaignId, now: datetime) -> bool:
        """Завершить running-кампанию в памяти."""
        stored = self.items.get(campaign_id)
        if stored is None or stored.status is not CampaignStatus.RUNNING:
            return False
        stored.status = CampaignStatus.COMPLETED
        stored.finished_at = now
        stored.updated_at = now
        return True


class FakeDebtorSnapshotRepository:
    """Репозиторий снимков должников в памяти."""

    def __init__(self) -> None:
        """Создать пустое хранилище."""
        self.items: dict[CampaignId, dict[str, DebtorSnapshot]] = {}

    async def replace_for_campaign(
        self,
        campaign_id: CampaignId,
        snapshots: Sequence[DebtorSnapshot],
    ) -> None:
        """Заменить снимок должников кампании."""
        self.items[campaign_id] = {
            str(snapshot.debtor.debtor_id): replace(snapshot) for snapshot in snapshots
        }

    async def count(self, campaign_id: CampaignId) -> int:
        """Вернуть число снимков кампании."""
        return len(self.items.get(campaign_id, {}))

    async def list(
        self,
        campaign_id: CampaignId,
        offset: int,
        limit: int,
    ) -> Sequence[DebtorSnapshot]:
        """Вернуть страницу снимков."""
        snapshots = sorted(
            self.items.get(campaign_id, {}).values(),
            key=lambda snapshot: str(snapshot.debtor.debtor_id),
        )
        return snapshots[offset : offset + limit]


class FakeNotificationMessageRepository:
    """Репозиторий сообщений в памяти."""

    def __init__(self) -> None:
        """Создать пустое хранилище."""
        self.items: dict[UUID, NotificationMessage] = {}

    async def add_many(self, messages: Sequence[NotificationMessage]) -> None:
        """Сохранить сообщения пачкой."""
        for message in messages:
            self.items[message.id] = replace(message)

    async def get(self, message_id: MessageId) -> NotificationMessage | None:
        """Вернуть сообщение или None."""
        stored = self.items.get(message_id)
        return None if stored is None else replace(stored)

    async def save(self, message: NotificationMessage) -> None:
        """Сохранить сообщение."""
        self.items[message.id] = replace(message)

    async def list_by_campaign(
        self,
        campaign_id: CampaignId,
        status: MessageStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NotificationMessage]:
        """Вернуть страницу сообщений кампании."""
        messages = [
            replace(message)
            for message in self.items.values()
            if message.campaign_id == campaign_id and (status is None or message.status is status)
        ]
        messages.sort(key=lambda message: (message.created_at, str(message.id)))
        return messages[offset : offset + limit]

    async def count_by_campaign(
        self,
        campaign_id: CampaignId,
        status: MessageStatus | None = None,
    ) -> int:
        """Вернуть число сообщений кампании."""
        return sum(
            1
            for message in self.items.values()
            if message.campaign_id == campaign_id and (status is None or message.status is status)
        )

    async def count_not_terminal(self, campaign_id: CampaignId) -> int:
        """Вернуть число незавершенных сообщений."""
        terminal = (
            MessageStatus.SENT,
            MessageStatus.FAILED,
            MessageStatus.CANCELLED,
        )
        return sum(
            1
            for message in self.items.values()
            if message.campaign_id == campaign_id and message.status not in terminal
        )

    async def cancel_pending(self, campaign_id: CampaignId) -> int:
        """Отменить неотправленные сообщения кампании."""
        cancelled = 0
        for identity, message in self.items.items():
            if message.campaign_id == campaign_id and message.cancel_if_pending():
                self.items[identity] = replace(message)
                cancelled += 1
        return cancelled


class FakeMessageAttemptRepository:
    """Репозиторий попыток отправки в памяти."""

    def __init__(self) -> None:
        """Создать пустое хранилище."""
        self.items: list[MessageAttempt] = []

    async def add(self, attempt: MessageAttempt) -> None:
        """Добавить попытку."""
        self.items.append(attempt)

    async def list_by_message(self, message_id: MessageId) -> Sequence[MessageAttempt]:
        """Вернуть попытки сообщения."""
        return [attempt for attempt in self.items if attempt.message_id == message_id]


class FakeCampaignEventOutbox:
    """Собирает события кампании текущей единицы работы."""

    def __init__(
        self,
        scheduled: list[CampaignScheduled],
        cancelled: list[CampaignCancelled],
        started: list[CampaignStart],
    ) -> None:
        """Сохранить списки событий."""
        self._scheduled = scheduled
        self._cancelled = cancelled
        self._started = started

    async def add_scheduled(
        self,
        event: CampaignScheduled,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Добавить campaign.scheduled."""
        self._scheduled.append(event)

    async def add_cancelled(
        self,
        event: CampaignCancelled,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Добавить campaign.cancelled."""
        self._cancelled.append(event)

    async def add_start(
        self,
        event: CampaignStart,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Добавить campaign.start."""
        self._started.append(event)


class FakeMaintenanceStore:
    """Хранилище обслуживания в памяти."""

    def __init__(self) -> None:
        """Создать пустое хранилище."""
        self.retry_due: list[NotificationMessage] = []
        self.stuck_campaigns: list[Campaign] = []
        self.completable_campaigns: list[Campaign] = []
        self.exhausted_commands: list[ExhaustedMessageCommand] = []
        self.failed_outbox: list[UUID] = []
        self.deleted_outbox = 0
        self.deleted_attempts = 0

    async def delete_published_outbox_before(self, cutoff: datetime) -> int:
        """Вернуть настроенное число удаленных записей outbox."""
        return self.deleted_outbox

    async def delete_attempts_before(self, cutoff: datetime) -> int:
        """Вернуть настроенное число удаленных попыток."""
        return self.deleted_attempts

    async def list_retry_due(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[NotificationMessage]:
        """Вернуть сообщения для повтора."""
        return self.retry_due[:limit]

    async def list_stuck_campaigns(
        self,
        before: datetime,
        limit: int,
    ) -> Sequence[Campaign]:
        """Вернуть зависшие кампании."""
        return self.stuck_campaigns[:limit]

    async def list_completable_campaigns(self, limit: int) -> Sequence[Campaign]:
        """Вернуть кампании для завершения."""
        return self.completable_campaigns[:limit]

    async def list_exhausted_message_send(
        self,
        max_attempts: int,
        limit: int,
    ) -> Sequence[ExhaustedMessageCommand]:
        """Вернуть команды с исчерпанными попытками outbox."""
        return self.exhausted_commands[:limit]

    async def mark_outbox_failed(self, outbox_id: UUID, failed_at: datetime) -> bool:
        """Зафиксировать отказ публикации записи outbox."""
        self.failed_outbox.append(outbox_id)
        return True


class FakeMessageCommandOutbox:
    """Собирает команды message.send текущей единицы работы."""

    def __init__(
        self,
        sink: list[NotificationCommand],
        delays: list[datetime | None],
    ) -> None:
        """Сохранить список команд и отложенных публикаций."""
        self._sink = sink
        self._delays = delays

    async def add(
        self,
        command: NotificationCommand,
        correlation_id: str,
        trace_id: str | None,
        occurred_at: datetime | None = None,
        available_at: datetime | None = None,
    ) -> None:
        """Добавить команду message.send и время готовности."""
        self._sink.append(command)
        self._delays.append(available_at)


class FakeUnitOfWork:
    """Единица работы в памяти с фиксацией только по commit."""

    def __init__(
        self,
        template_repository: FakeTemplateRepository,
        campaign_repository: FakeCampaignRepository,
        snapshot_repository: FakeDebtorSnapshotRepository,
        message_repository: FakeNotificationMessageRepository,
        attempt_repository: FakeMessageAttemptRepository,
        maintenance_store: FakeMaintenanceStore,
        committed_audits: list[AuditEvent],
        scheduled_events: list[CampaignScheduled],
        cancelled_events: list[CampaignCancelled],
        start_events: list[CampaignStart],
        message_commands: list[NotificationCommand],
        message_delays: list[datetime | None],
    ) -> None:
        """Создать репозитории и буферы исходящих событий."""
        self.templates: NotificationTemplateRepository = template_repository
        self.campaigns: CampaignRepository = campaign_repository
        self.snapshots: DebtorSnapshotRepository = snapshot_repository
        self.messages: NotificationMessageRepository = message_repository
        self.attempts: MessageAttemptRepository = attempt_repository
        self.maintenance: MaintenanceStore = maintenance_store
        self._committed_audits = committed_audits
        self._committed_scheduled = scheduled_events
        self._committed_cancelled = cancelled_events
        self._committed_started = start_events
        self._committed_commands = message_commands
        self._pending_audits: list[AuditEvent] = []
        self._pending_scheduled: list[CampaignScheduled] = []
        self._pending_cancelled: list[CampaignCancelled] = []
        self._pending_started: list[CampaignStart] = []
        self._pending_commands: list[NotificationCommand] = []
        self.audit: AuditEventOutbox = FakeAuditOutbox(self._pending_audits)
        self.events: CampaignEventOutbox = FakeCampaignEventOutbox(
            self._pending_scheduled,
            self._pending_cancelled,
            self._pending_started,
        )
        self.message_commands: MessageCommandOutbox = FakeMessageCommandOutbox(
            self._pending_commands,
            message_delays,
        )
        self.committed = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        """Открыть единицу работы."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        """Отбросить незафиксированные события."""
        self._pending_audits.clear()
        self._pending_scheduled.clear()
        self._pending_cancelled.clear()
        self._pending_started.clear()
        self._pending_commands.clear()

    async def commit(self) -> None:
        """Перенести события в зафиксированные списки."""
        self._committed_audits.extend(self._pending_audits)
        self._committed_scheduled.extend(self._pending_scheduled)
        self._committed_cancelled.extend(self._pending_cancelled)
        self._committed_started.extend(self._pending_started)
        self._committed_commands.extend(self._pending_commands)
        self._pending_audits.clear()
        self._pending_scheduled.clear()
        self._pending_cancelled.clear()
        self._pending_started.clear()
        self._pending_commands.clear()
        self.committed = True


class FakeUnitOfWorkFactory:
    """Создаёт единицы работы поверх общих репозиториев."""

    def __init__(self) -> None:
        """Создать пустые репозитории и списки событий."""
        self.repository = FakeTemplateRepository()
        self.campaigns = FakeCampaignRepository()
        self.snapshots = FakeDebtorSnapshotRepository()
        self.messages = FakeNotificationMessageRepository()
        self.attempts = FakeMessageAttemptRepository()
        self.maintenance = FakeMaintenanceStore()
        self.audits: list[AuditEvent] = []
        self.scheduled_events: list[CampaignScheduled] = []
        self.cancelled_events: list[CampaignCancelled] = []
        self.start_events: list[CampaignStart] = []
        self.message_commands: list[NotificationCommand] = []
        self.message_delays: list[datetime | None] = []
        self.units: list[FakeUnitOfWork] = []

    def __call__(self) -> UnitOfWork:
        """Вернуть новую единицу работы."""
        unit = FakeUnitOfWork(
            self.repository,
            self.campaigns,
            self.snapshots,
            self.messages,
            self.attempts,
            self.maintenance,
            self.audits,
            self.scheduled_events,
            self.cancelled_events,
            self.start_events,
            self.message_commands,
            self.message_delays,
        )
        self.units.append(unit)
        return unit


class NotificationsHarness:
    """Набор зависимостей для тестов сценариев Notifications.

    Attributes:
        service: Сервис шаблонов на тестовых двойниках.
        campaign_service: Сервис кампаний на тестовых двойниках.
        repository: Репозиторий шаблонов в памяти.
        campaigns: Репозиторий кампаний в памяти.
        audits: Зафиксированные audit-события.
        scheduled_events: Зафиксированные campaign.scheduled.
        cancelled_events: Зафиксированные campaign.cancelled.
        start_events: Зафиксированные campaign.start.
        message_commands: Зафиксированные команды message.send.
        snapshots: Репозиторий снимков должников.
        messages: Репозиторий сообщений.
        factory: Фабрика единиц работы.
        clock: Управляемые часы.
    """

    def __init__(self) -> None:
        """Собрать сервисы и двойники."""
        self.clock = FixedClock(datetime(2026, 11, 22, 12, 0, tzinfo=UTC))
        self.factory = FakeUnitOfWorkFactory()
        self.service = TemplateService(uow_factory=self.factory, clock=self.clock)
        self.campaign_service = CampaignService(
            uow_factory=self.factory,
            clock=self.clock,
        )
        self.repository = self.factory.repository
        self.campaigns = self.factory.campaigns
        self.snapshots = self.factory.snapshots
        self.messages = self.factory.messages
        self.attempts = self.factory.attempts
        self.maintenance = self.factory.maintenance
        self.audits = self.factory.audits
        self.scheduled_events = self.factory.scheduled_events
        self.cancelled_events = self.factory.cancelled_events
        self.start_events = self.factory.start_events
        self.message_commands = self.factory.message_commands
        self.message_command_delays = self.factory.message_delays

    async def create_active_template(
        self,
        key: str = "payment-reminder",
        version: int = 1,
    ) -> NotificationTemplate:
        """Создать и активировать версию шаблона."""
        context = RequestContext(correlation_id="harness", trace_id=None)
        template = await self.service.create_template(
            CreateTemplateCommand(
                key=key,
                version=version,
                description="Шаблон для тестов",
                required_variables=("debtor_name", "amount"),
            ),
            context,
        )
        return await self.service.update_status(
            template.key,
            template.version,
            TemplateStatus.ACTIVE,
            context,
        )


@pytest.fixture
def template_harness() -> NotificationsHarness:
    """Вернуть набор зависимостей для тестов шаблонов."""
    return NotificationsHarness()


@pytest.fixture
def campaign_harness() -> NotificationsHarness:
    """Вернуть набор зависимостей для тестов кампаний."""
    return NotificationsHarness()


@pytest.fixture
def fake_abs_source_factory() -> Callable[..., AbsDebtorSource]:
    """Вернуть фабрику тестового источника АБС."""

    def create(
        debtors: tuple[AbsDebtor, ...] | None = None,
        failure: FailureMode | None = None,
    ) -> AbsDebtorSource:
        return FakeAbsDebtorSource(debtors=debtors, failure=failure)

    return create
