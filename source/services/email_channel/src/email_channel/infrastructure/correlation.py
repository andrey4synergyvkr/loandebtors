"""Контекст корреляции запросов и сообщений."""

from contextvars import ContextVar, Token
from uuid import uuid4

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    """Создать новый идентификатор корреляции."""
    return uuid4().hex


def bind_correlation_id(value: str) -> Token[str | None]:
    """Привязать идентификатор корреляции к текущему контексту."""
    return _correlation_id.set(value)


def reset_correlation_id(token: Token[str | None]) -> None:
    """Восстановить предыдущий идентификатор корреляции."""
    _correlation_id.reset(token)


def get_correlation_id() -> str | None:
    """Вернуть текущий идентификатор корреляции."""
    return _correlation_id.get()
