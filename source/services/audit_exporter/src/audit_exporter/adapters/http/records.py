"""Read-only маршруты выгрузки журнала аудита."""

import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import AwareDatetime

from audit_exporter.adapters.http.constants import (
    AUDIT_RECORD_PATH,
    AUDIT_RECORDS_PATH,
    AUDIT_TAG,
)
from audit_exporter.adapters.http.problems import PROBLEM_MEDIA_TYPE, Problem
from audit_exporter.adapters.http.schemas import (
    AuditPageResponse,
    AuditRecordResponse,
    page_to_response,
    record_to_response,
)
from audit_exporter.application.audit_reader import AuditReader, RequestContext
from audit_exporter.domain import (
    CHANNEL_PATTERN,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    AuditAction,
    AuditEventId,
    AuditFilter,
    CampaignId,
    Channel,
)
from audit_exporter.infrastructure.correlation import get_correlation_id, new_correlation_id
from audit_exporter.infrastructure.metrics import Metrics
from audit_exporter.infrastructure.tracing import current_trace_id

router = APIRouter()


def _problem_response(description: str) -> dict[str, Any]:
    """Описать ответ Problem с media type application/problem+json."""
    return {
        "description": description,
        "content": {
            PROBLEM_MEDIA_TYPE: {
                "schema": Problem.model_json_schema(),
            }
        },
    }


@router.get(
    AUDIT_RECORDS_PATH,
    response_model=AuditPageResponse,
    operation_id="listAuditRecords",
    tags=[AUDIT_TAG],
    responses={
        422: _problem_response("Ошибка валидации запроса"),
        500: _problem_response("Внутренняя ошибка сервиса"),
    },
)
async def list_audit_records(
    request: Request,
    campaign_id: Annotated[UUID | None, Query()] = None,
    channel: Annotated[str | None, Query(pattern=CHANNEL_PATTERN, max_length=64)] = None,
    action: Annotated[AuditAction | None, Query()] = None,
    occurred_from: Annotated[AwareDatetime | None, Query()] = None,
    occurred_to: Annotated[AwareDatetime | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> AuditPageResponse:
    """Вернуть страницу журнала аудита."""
    reader: AuditReader = request.app.state.audit_reader
    filters = AuditFilter(
        campaign_id=CampaignId(campaign_id) if campaign_id is not None else None,
        channel=Channel(channel) if channel is not None else None,
        action=action,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        cursor=cursor,
        limit=limit,
    )
    context = RequestContext(
        correlation_id=get_correlation_id() or new_correlation_id(),
        trace_id=current_trace_id(),
    )
    metrics: Metrics = request.app.state.metrics
    started_at = time.monotonic()
    page = await reader.list_records(filters, context)
    metrics.audit_query_duration.record(time.monotonic() - started_at)
    metrics.audit_records_returned.record(len(page.items))
    return page_to_response(page)


@router.get(
    AUDIT_RECORD_PATH,
    response_model=AuditRecordResponse,
    operation_id="getAuditRecord",
    tags=[AUDIT_TAG],
    responses={
        404: _problem_response("Запись не найдена"),
        422: _problem_response("Ошибка валидации запроса"),
        500: _problem_response("Внутренняя ошибка сервиса"),
    },
)
async def get_audit_record(request: Request, event_id: UUID) -> AuditRecordResponse:
    """Вернуть запись журнала по идентификатору события."""
    reader: AuditReader = request.app.state.audit_reader
    context = RequestContext(
        correlation_id=get_correlation_id() or new_correlation_id(),
        trace_id=current_trace_id(),
    )
    record = await reader.get_record(AuditEventId(event_id), context)
    return record_to_response(record)
