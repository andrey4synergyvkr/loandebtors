"""Сценарий чтения журнала аудита и фиксации выгрузки."""

from dataclasses import dataclass
from datetime import UTC, datetime
from re import fullmatch
from uuid import uuid4

from audit_exporter.domain import (
    AUDIT_ENTITY_TYPE,
    AUDIT_EXPORTER_SERVICE,
    AUDIT_RECORDS_ENTITY_ID,
    CHANNEL_PATTERN,
    MAX_PAGE_SIZE,
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
from audit_exporter.ports.audit import AuditStore
from audit_exporter.ports.clock import Clock


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Контекст HTTP-запроса для audit-события выгрузки.

    Attributes:
        correlation_id: Идентификатор сценария.
        trace_id: Идентификатор активного трейса.
    """

    correlation_id: str
    trace_id: str | None


class AuditReader:
    """Читает журнал и фиксирует факт выгрузки на первой странице."""

    def __init__(self, store: AuditStore, clock: Clock) -> None:
        """Сохранить хранилище и часы."""
        self._store = store
        self._clock = clock

    async def list_records(self, filters: AuditFilter, context: RequestContext) -> AuditPage:
        """Вернуть страницу журнала и записать audit.exported на первой странице."""
        self._validate(filters)
        page = await self._store.query(filters)
        if filters.cursor is None:
            await self._record_export(filters, len(page.items), context)
        return page

    async def get_record(
        self,
        event_id: AuditEventId,
        context: RequestContext | None = None,
    ) -> AuditRecord:
        """Вернуть запись по event_id или ошибку NotFoundError."""
        record = await self._store.get_by_event_id(event_id)
        if record is None:
            raise NotFoundError("Запись журнала не найдена")
        if context is not None:
            await self._append_export_event(
                details={
                    "endpoint": "audit-record",
                    "event_id": str(record.event.event_id),
                    "sequence": str(record.sequence),
                },
                campaign_id=record.event.campaign_id,
                channel=record.event.channel,
                context=context,
            )
        return record

    @staticmethod
    def _validate(filters: AuditFilter) -> None:
        """Проверить диапазон времени, лимит и шаблон канала."""
        if filters.limit < 1 or filters.limit > MAX_PAGE_SIZE:
            raise ValidationError(f"limit должен быть от 1 до {MAX_PAGE_SIZE}")
        if filters.occurred_from is not None and filters.occurred_from.tzinfo is None:
            raise ValidationError("occurred_from должен содержать часовой пояс")
        if filters.occurred_to is not None and filters.occurred_to.tzinfo is None:
            raise ValidationError("occurred_to должен содержать часовой пояс")
        if (
            filters.occurred_from is not None
            and filters.occurred_to is not None
            and filters.occurred_from >= filters.occurred_to
        ):
            raise ValidationError("occurred_from должен быть меньше occurred_to")
        if filters.channel is not None and fullmatch(CHANNEL_PATTERN, filters.channel) is None:
            raise ValidationError("channel не соответствует шаблону")

    async def _record_export(
        self,
        filters: AuditFilter,
        returned: int,
        context: RequestContext,
    ) -> None:
        """Записать событие audit.exported в журнал."""
        details: dict[str, str] = {
            "endpoint": AUDIT_RECORDS_ENTITY_ID,
            "limit": str(filters.limit),
            "returned": str(returned),
        }
        if filters.campaign_id is not None:
            details["campaign_id"] = str(filters.campaign_id)
        if filters.channel is not None:
            details["channel"] = filters.channel
        if filters.action is not None:
            details["action"] = filters.action.value
        if filters.occurred_from is not None:
            details["occurred_from"] = _to_iso(filters.occurred_from)
        if filters.occurred_to is not None:
            details["occurred_to"] = _to_iso(filters.occurred_to)
        await self._append_export_event(
            details=details,
            campaign_id=filters.campaign_id,
            channel=filters.channel,
            context=context,
        )

    async def _append_export_event(
        self,
        *,
        details: dict[str, str],
        campaign_id: CampaignId | None,
        channel: Channel | None,
        context: RequestContext,
    ) -> None:
        """Записать событие audit.exported с заданными деталями."""
        event = AuditEvent(
            event_id=AuditEventId(uuid4()),
            occurred_at=self._clock.now(),
            service=AUDIT_EXPORTER_SERVICE,
            actor=AuditActor(type=AuditActorType.ADMINISTRATOR, identifier=None),
            action=AuditAction.AUDIT_EXPORTED,
            entity_type=AUDIT_ENTITY_TYPE,
            entity_id=AUDIT_RECORDS_ENTITY_ID,
            campaign_id=campaign_id,
            message_id=None,
            channel=channel,
            outcome=AuditOutcome.SUCCESS,
            details=details,
            correlation_id=context.correlation_id or uuid4().hex,
            trace_id=context.trace_id,
        )
        await self._store.append(event)


def _to_iso(value: datetime) -> str:
    """Привести время к UTC и вернуть ISO-строку."""
    return value.astimezone(UTC).isoformat()
