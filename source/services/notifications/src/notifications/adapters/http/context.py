"""Контекст HTTP-запроса для audit-событий."""

from notifications.application.common import RequestContext
from notifications.infrastructure.correlation import (
    get_correlation_id,
    new_correlation_id,
)
from notifications.infrastructure.tracing import current_trace_id


def build_request_context() -> RequestContext:
    """Собрать контекст корреляции и трейса для аудита."""
    return RequestContext(
        correlation_id=get_correlation_id() or new_correlation_id(),
        trace_id=current_trace_id(),
    )
