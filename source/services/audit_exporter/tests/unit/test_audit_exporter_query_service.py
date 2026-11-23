"""Проверка сценария чтения журнала и self-audit."""

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from audit_exporter.application.audit_reader import AuditReader, RequestContext
from audit_exporter.domain import (
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditFilter,
    AuditOutcome,
    AuditPage,
    AuditRecord,
    CampaignId,
    Channel,
    NotFoundError,
    ValidationError,
)
from audit_exporter.ports import AuditStore

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
_EVENT_ID = UUID("3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d")
_CAMPAIGN_ID = UUID("5a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d")


class FakeClock:
    """Часы с фиксированным временем."""

    def now(self) -> datetime:
        """Вернуть фиксированное время."""
        return _NOW


class FakeStore:
    """Хранилище с заранее заданной страницей."""

    def __init__(self, page: AuditPage, record: AuditRecord | None = None) -> None:
        """Сохранить страницу и запись."""
        self.page = page
        self.record = record
        self.appended: list[AuditEvent] = []
        self.filters: AuditFilter | None = None
        self.requested_event_id: AuditEventId | None = None

    async def append(self, event: AuditEvent) -> None:
        """Запомнить добавленное событие."""
        self.appended.append(event)

    async def query(self, filters: AuditFilter) -> AuditPage:
        """Вернуть заданную страницу."""
        self.filters = filters
        return self.page

    async def get_by_event_id(self, event_id: AuditEventId) -> AuditRecord | None:
        """Вернуть заданную запись."""
        self.requested_event_id = event_id
        return self.record


def _event() -> AuditEvent:
    return AuditEvent(
        event_id=AuditEventId(_EVENT_ID),
        occurred_at=_NOW,
        service="notifications",
        actor=AuditActor(type=AuditActorType.SYSTEM, identifier="notifications"),
        action=AuditAction.MESSAGE_SENT,
        entity_type="message",
        entity_id=str(_EVENT_ID),
        campaign_id=CampaignId(_CAMPAIGN_ID),
        message_id=None,
        channel=Channel("email"),
        outcome=AuditOutcome.SUCCESS,
        details={"provider": "mailpit"},
        correlation_id="corr-1",
        trace_id=None,
    )


def _record() -> AuditRecord:
    return AuditRecord(sequence=1, event=_event(), ingested_at=_NOW)


def _reader(store: FakeStore) -> AuditReader:
    return AuditReader(cast(AuditStore, store), FakeClock())


async def test_list_records_records_export_on_first_page() -> None:
    """Первая страница добавляет audit.exported с фильтрами и контекстом."""
    store = FakeStore(AuditPage(items=(_record(),), next_cursor="next"))
    filters = AuditFilter(
        campaign_id=CampaignId(_CAMPAIGN_ID),
        channel=Channel("email"),
        action=AuditAction.MESSAGE_SENT,
        occurred_from=datetime(2026, 11, 1, tzinfo=UTC),
        occurred_to=datetime(2026, 11, 30, tzinfo=UTC),
        limit=10,
    )

    page = await _reader(store).list_records(filters, RequestContext("corr", "trace"))

    assert page.items == (_record(),)
    assert page.next_cursor == "next"
    assert store.filters == filters
    assert len(store.appended) == 1
    export = store.appended[0]
    assert export.action is AuditAction.AUDIT_EXPORTED
    assert export.service == "audit_exporter"
    assert export.actor.type is AuditActorType.ADMINISTRATOR
    assert export.outcome is AuditOutcome.SUCCESS
    assert export.campaign_id == filters.campaign_id
    assert export.channel == filters.channel
    assert export.details["limit"] == "10"
    assert export.details["returned"] == "1"
    assert export.details["action"] == "message.sent"
    assert export.details["campaign_id"] == str(_CAMPAIGN_ID)
    assert export.correlation_id == "corr"
    assert export.trace_id == "trace"


async def test_list_records_does_not_record_export_for_cursor_page() -> None:
    """Страница с курсором не создаёт повторное audit.exported."""
    store = FakeStore(AuditPage(items=(), next_cursor=None))
    filters = AuditFilter(cursor="cursor", limit=10)

    await _reader(store).list_records(filters, RequestContext("corr", None))

    assert store.appended == []


@pytest.mark.parametrize(
    "filters",
    [
        AuditFilter(limit=0),
        AuditFilter(limit=1001),
        AuditFilter(occurred_from=datetime(2026, 11, 22)),
        AuditFilter(occurred_to=datetime(2026, 11, 22)),
        AuditFilter(
            occurred_from=datetime(2026, 11, 22, tzinfo=UTC),
            occurred_to=datetime(2026, 11, 21, tzinfo=UTC),
        ),
        AuditFilter(channel=Channel("Email!")),
    ],
)
async def test_invalid_filter_raises_validation_error(filters: AuditFilter) -> None:
    """Некорректные фильтры отклоняются до запроса в БД."""
    store = FakeStore(AuditPage(items=(), next_cursor=None))

    with pytest.raises(ValidationError):
        await _reader(store).list_records(filters, RequestContext("corr", None))

    assert store.filters is None


async def test_get_record_returns_record_and_records_export() -> None:
    """Чтение по event_id возвращается и фиксируется как audit.exported."""
    record = _record()
    store = FakeStore(AuditPage(items=(), next_cursor=None), record=record)

    result = await _reader(store).get_record(
        AuditEventId(_EVENT_ID),
        RequestContext("corr", "trace"),
    )

    assert result == record
    assert store.requested_event_id == _EVENT_ID
    assert len(store.appended) == 1
    export = store.appended[0]
    assert export.action is AuditAction.AUDIT_EXPORTED
    assert export.details["endpoint"] == "audit-record"
    assert export.details["event_id"] == str(_EVENT_ID)
    assert export.details["sequence"] == "1"
    assert export.campaign_id == record.event.campaign_id
    assert export.channel == record.event.channel
    assert export.correlation_id == "corr"
    assert export.trace_id == "trace"


async def test_get_record_without_context_does_not_record_export() -> None:
    """Внутреннее чтение без контекста не создаёт audit.exported."""
    record = _record()
    store = FakeStore(AuditPage(items=(), next_cursor=None), record=record)

    result = await _reader(store).get_record(AuditEventId(_EVENT_ID))

    assert result == record
    assert store.appended == []


async def test_get_record_raises_not_found() -> None:
    """Отсутствующая запись даёт NotFoundError."""
    store = FakeStore(AuditPage(items=(), next_cursor=None), record=None)

    with pytest.raises(NotFoundError):
        await _reader(store).get_record(AuditEventId(uuid4()))
