"""Проверка trace context в audit-outbox Scheduler."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from opentelemetry import propagate
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, use_span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.adapters.persistence.event_outbox import SqlAlchemyEventOutbox
from scheduler.domain.audit import (
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditOutcome,
)
from scheduler.domain.ids import AuditEventId, CampaignId

_TRACE_ID = 0x1234567890ABCDEF1234567890ABCDEF
_SPAN_ID = 0x1234567890ABCDEF


class FakeSession:
    """Сессия, которая запоминает добавленные строки."""

    def __init__(self) -> None:
        """Создать пустой список строк."""
        self.rows: list[Any] = []

    def add(self, row: object) -> None:
        """Запомнить строку outbox."""
        self.rows.append(row)


def _event() -> AuditEvent:
    return AuditEvent(
        event_id=AuditEventId(uuid4()),
        occurred_at=datetime(2026, 11, 22, 12, 0, tzinfo=UTC),
        service="scheduler",
        actor=AuditActor(type=AuditActorType.SYSTEM, identifier="scheduler"),
        action=AuditAction.CAMPAIGN_SCHEDULED,
        entity_type="campaign",
        entity_id=str(uuid4()),
        campaign_id=CampaignId(uuid4()),
        outcome=AuditOutcome.SUCCESS,
        details={"kind": "one_off"},
        correlation_id="corr-1",
        trace_id=format(_TRACE_ID, "032x"),
    )


async def test_audit_outbox_injects_traceparent_header() -> None:
    """Активный span попадает в заголовки outbox как traceparent."""
    session = FakeSession()
    outbox = SqlAlchemyEventOutbox(cast(AsyncSession, session))
    span_context = SpanContext(
        trace_id=_TRACE_ID,
        span_id=_SPAN_ID,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    previous = propagate.get_global_textmap()
    propagate.set_global_textmap(TraceContextTextMapPropagator())
    try:
        with use_span(NonRecordingSpan(span_context), end_on_exit=False):
            await outbox.add_audit(_event())
    finally:
        propagate.set_global_textmap(previous)

    row = session.rows[0]
    headers = row.headers
    assert headers["correlation_id"] == "corr-1"
    assert headers["traceparent"] == f"00-{_TRACE_ID:032x}-{_SPAN_ID:016x}-01"
