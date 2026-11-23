"""Эндпоинт проверки работоспособности заглушки."""

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict

from abs.adapters.http.constants import (
    HEALTH_PATH,
    HEALTH_UNAVAILABLE_DESCRIPTION,
    SYSTEM_TAG,
)
from abs.application.health import HealthService, HealthSnapshot, HealthStatus

router = APIRouter(tags=[SYSTEM_TAG])


class HealthCheckResponse(BaseModel):
    """Результат одной проверки.

    Attributes:
        name: Имя проверки.
        status: Статус проверки.
        detail: Пояснение для оператора.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    status: HealthStatus
    detail: str | None = None


class HealthResponse(BaseModel):
    """Ответ проверки работоспособности.

    Attributes:
        status: Итоговый статус.
        service: Имя сервиса.
        version: Версия сервиса.
        uptime_seconds: Время работы процесса в секундах.
        checks: Результаты проверок.
    """

    model_config = ConfigDict(extra="forbid")

    status: HealthStatus
    service: str
    version: str
    uptime_seconds: float
    checks: list[HealthCheckResponse]


@router.get(
    HEALTH_PATH,
    response_model=HealthResponse,
    operation_id="getHealth",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": HealthResponse,
            "description": HEALTH_UNAVAILABLE_DESCRIPTION,
        }
    },
)
async def get_health(request: Request, response: Response) -> HealthResponse:
    """Вернуть честное состояние заглушки."""
    service: HealthService = request.app.state.health
    snapshot: HealthSnapshot = await service.snapshot()
    if snapshot.status is HealthStatus.UNAVAILABLE:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status=snapshot.status,
        service=snapshot.service,
        version=snapshot.version,
        uptime_seconds=snapshot.uptime_seconds,
        checks=[
            HealthCheckResponse(name=check.name, status=check.status, detail=check.detail)
            for check in snapshot.checks
        ],
    )
