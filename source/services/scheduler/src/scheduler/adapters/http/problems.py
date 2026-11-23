"""Модель Problem и обработчики ошибок."""

import logging
from typing import Final

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE: Final = "application/problem+json"
INTERNAL_ERROR_TYPE: Final = "urn:loandebtors:error:internal"
INTERNAL_ERROR_TITLE: Final = "Internal Server Error"
INTERNAL_ERROR_CODE: Final = "internal_error"


class Problem(BaseModel):
    """Описание ошибки по RFC 9457.

    Attributes:
        type: URI типа ошибки.
        title: Краткое название.
        status: HTTP-код.
        detail: Пояснение для клиента.
        instance: URI конкретного запроса.
        code: Машинный код ошибки.
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str | None = None


class ProblemResponse(JSONResponse):
    """Ответ в формате application/problem+json."""

    media_type = PROBLEM_MEDIA_TYPE


def internal_error(detail: str = "Внутренняя ошибка сервиса") -> Problem:
    """Собрать Problem для непредвиденной ошибки."""
    return Problem(
        type=INTERNAL_ERROR_TYPE,
        title=INTERNAL_ERROR_TITLE,
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail,
        code=INTERNAL_ERROR_CODE,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> ProblemResponse:
    """Вернуть Problem вместо стандартного ответа FastAPI."""
    logger.exception("Необработанная ошибка при обработке запроса %s", request.url.path)
    problem = internal_error()
    return ProblemResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=problem.model_dump(exclude_none=True),
    )
