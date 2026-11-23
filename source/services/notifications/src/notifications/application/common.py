"""Общие типы сценариев приложения."""

from dataclasses import dataclass
from typing import Final

from notifications.domain import ValidationError

DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 200


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Контекст HTTP-запроса для audit-событий.

    Attributes:
        correlation_id: Идентификатор сценария.
        trace_id: Идентификатор активного OTel-трейса.
    """

    correlation_id: str
    trace_id: str | None


def validate_page(limit: int, offset: int) -> None:
    """Проверить размер страницы и смещение.

    Raises:
        ValidationError: Размер страницы или смещение недопустимы.
    """
    if limit < 1 or limit > MAX_PAGE_SIZE:
        raise ValidationError(f"limit должен быть от 1 до {MAX_PAGE_SIZE}")
    if offset < 0:
        raise ValidationError("offset не может быть отрицательным")
