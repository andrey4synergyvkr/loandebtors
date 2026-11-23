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

VALIDATION_ERROR_TYPE: Final = "urn:loandebtors:error:validation"
VALIDATION_ERROR_TITLE: Final = "Unprocessable Content"
VALIDATION_ERROR_CODE: Final = "validation_error"

UNAVAILABLE_TYPE: Final = "urn:loandebtors:error:abs-unavailable"
UNAVAILABLE_TITLE: Final = "Service Unavailable"
UNAVAILABLE_CODE: Final = "abs_unavailable"

INVALID_SCENARIO_TYPE: Final = "urn:loandebtors:error:invalid-stub-scenario"
INVALID_SCENARIO_TITLE: Final = "Bad Request"
INVALID_SCENARIO_CODE: Final = "invalid_stub_scenario"


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


def problem_response(problem: Problem) -> ProblemResponse:
    """Собрать HTTP-ответ из описания ошибки."""
    return ProblemResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
    )


def internal_error(detail: str = "Внутренняя ошибка сервиса") -> Problem:
    """Собрать Problem для непредвиденной ошибки."""
    return Problem(
        type=INTERNAL_ERROR_TYPE,
        title=INTERNAL_ERROR_TITLE,
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail,
        code=INTERNAL_ERROR_CODE,
    )


def validation_error(detail: str = "Параметры запроса не прошли проверку") -> Problem:
    """Собрать Problem для некорректного запроса."""
    return Problem(
        type=VALIDATION_ERROR_TYPE,
        title=VALIDATION_ERROR_TITLE,
        status=422,
        detail=detail,
        code=VALIDATION_ERROR_CODE,
    )


def unavailable(detail: str = "АБС недоступна") -> Problem:
    """Собрать Problem для недоступной АБС."""
    return Problem(
        type=UNAVAILABLE_TYPE,
        title=UNAVAILABLE_TITLE,
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
        code=UNAVAILABLE_CODE,
    )


def invalid_scenario(detail: str) -> Problem:
    """Собрать Problem для неизвестного сценария заглушки."""
    return Problem(
        type=INVALID_SCENARIO_TYPE,
        title=INVALID_SCENARIO_TITLE,
        status=status.HTTP_400_BAD_REQUEST,
        detail=detail,
        code=INVALID_SCENARIO_CODE,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> ProblemResponse:
    """Вернуть Problem вместо стандартного ответа FastAPI."""
    logger.exception("Необработанная ошибка при обработке запроса %s", request.url.path)
    return problem_response(internal_error())


async def validation_exception_handler(
    request: Request,
    _exc: Exception,
) -> ProblemResponse:
    """Вернуть Problem для ошибок валидации параметров."""
    logger.info("Параметры запроса не прошли проверку: %s", request.url.path)
    return problem_response(validation_error())
