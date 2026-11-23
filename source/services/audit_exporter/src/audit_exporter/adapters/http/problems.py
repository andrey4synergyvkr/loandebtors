"""Модель Problem и обработчики ошибок."""

import logging
from typing import Final

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from audit_exporter.domain import NotFoundError
from audit_exporter.domain import ValidationError as DomainValidationError

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE: Final = "application/problem+json"
VALIDATION_TYPE: Final = "urn:loandebtors:error:validation"
VALIDATION_TITLE: Final = "Unprocessable Entity"
VALIDATION_CODE: Final = "validation_error"
NOT_FOUND_TYPE: Final = "urn:loandebtors:error:not-found"
NOT_FOUND_TITLE: Final = "Not Found"
NOT_FOUND_CODE: Final = "not_found"
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


def validation_error(detail: str) -> Problem:
    """Собрать Problem для ошибки валидации запроса."""
    return Problem(
        type=VALIDATION_TYPE,
        title=VALIDATION_TITLE,
        status=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=detail,
        code=VALIDATION_CODE,
    )


def not_found(detail: str) -> Problem:
    """Собрать Problem для отсутствующего объекта."""
    return Problem(
        type=NOT_FOUND_TYPE,
        title=NOT_FOUND_TITLE,
        status=status.HTTP_404_NOT_FOUND,
        detail=detail,
        code=NOT_FOUND_CODE,
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


async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> ProblemResponse:
    """Вернуть 422 Problem для ошибки валидации параметров FastAPI."""
    problem = validation_error(_format_validation_errors(exc))
    return _response(problem, request)


async def domain_validation_exception_handler(
    request: Request,
    exc: DomainValidationError,
) -> ProblemResponse:
    """Вернуть 422 Problem для ошибки доменной валидации."""
    problem = validation_error(str(exc))
    return _response(problem, request)


async def not_found_exception_handler(
    request: Request,
    exc: NotFoundError,
) -> ProblemResponse:
    """Вернуть 404 Problem для отсутствующей записи."""
    problem = not_found(str(exc))
    return _response(problem, request)


async def unhandled_exception_handler(request: Request, exc: Exception) -> ProblemResponse:
    """Вернуть 500 Problem вместо стандартного ответа FastAPI."""
    logger.exception("Необработанная ошибка при обработке запроса %s", request.url.path)
    return _response(internal_error(), request)


def _response(problem: Problem, request: Request) -> ProblemResponse:
    """Собрать ProblemResponse с instance текущего запроса."""
    problem = problem.model_copy(update={"instance": request.url.path})
    return ProblemResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
    )


def _format_validation_errors(exc: RequestValidationError) -> str:
    """Собрать короткое описание ошибок валидации без раскрытия данных."""
    parts: list[str] = []
    for error in exc.errors()[:5]:
        location = ".".join(str(item) for item in error.get("loc", ()))
        message = str(error.get("msg", "ошибка"))
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts) or "Ошибка валидации запроса"
