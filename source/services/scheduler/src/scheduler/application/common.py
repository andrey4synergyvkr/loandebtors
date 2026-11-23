"""Общие типы сценариев приложения Scheduler."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MessageContext:
    """Контекст входящего сообщения для audit-событий.

    Attributes:
        correlation_id: Идентификатор сценария.
        trace_id: Идентификатор активного OTel-трейса.
    """

    correlation_id: str
    trace_id: str | None
