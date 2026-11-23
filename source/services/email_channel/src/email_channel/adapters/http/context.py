"""Сборка контекста HTTP-запроса для audit-событий."""

from email_channel.application.config import RequestContext
from email_channel.infrastructure.correlation import get_correlation_id, new_correlation_id
from email_channel.infrastructure.tracing import current_trace_id


def build_request_context() -> RequestContext:
    """Вернуть correlation_id и trace_id текущего запроса."""
    return RequestContext(
        correlation_id=get_correlation_id() or new_correlation_id(),
        trace_id=current_trace_id(),
    )
