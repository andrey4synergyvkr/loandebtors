"""Текущий trace context для логов и audit-событий."""

from opentelemetry.trace import get_current_span


def current_trace_id() -> str | None:
    """Вернуть trace_id активного спана или None."""
    span_context = get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return format(span_context.trace_id, "032x")
