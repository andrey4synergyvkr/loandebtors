"""Точка входа заглушки АБС."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import metadata
from typing import Final

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from abs.adapters.fixture import JsonDebtorCatalog
from abs.adapters.http.debtors import router as debtors_router
from abs.adapters.http.health import router as health_router
from abs.adapters.http.middleware import CorrelationIdMiddleware, HttpMetricsMiddleware
from abs.adapters.http.problems import (
    unhandled_exception_handler,
    validation_exception_handler,
)
from abs.application.health import ApplicationState, HealthService
from abs.config import Settings, get_settings
from abs.container import build_container
from abs.infrastructure.logging import configure_logging
from abs.infrastructure.metrics import Metrics
from abs.infrastructure.telemetry import TelemetryRuntime, create_telemetry

PACKAGE_NAME: Final = "loandebtors-abs"
_UNKNOWN_VERSION: Final = "unknown"

logger = logging.getLogger(__name__)


def _resolve_version() -> str:
    """Вернуть версию установленного пакета или unknown."""
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return _UNKNOWN_VERSION


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Отметить готовность и корректно освободить ресурсы."""
    health: HealthService = app.state.health
    health.mark_ready()
    try:
        yield
    finally:
        health.begin_shutdown()
        telemetry: TelemetryRuntime | None = app.state.telemetry
        if telemetry is not None:
            telemetry.shutdown()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Собрать приложение FastAPI."""
    current = settings or get_settings()
    version = _resolve_version()
    telemetry = create_telemetry(current, version)
    configure_logging(
        current.log_level,
        current.service_name,
        current.environment,
        version,
        telemetry.logger_provider if telemetry is not None else None,
    )
    container = build_container(current)
    metrics: Metrics = container.resolve(Metrics)
    catalog: JsonDebtorCatalog = container.resolve(JsonDebtorCatalog)

    app = FastAPI(
        title="LoanDebtors ABS (stub)",
        version=version,
        lifespan=lifespan,
    )
    application_state = ApplicationState(
        service=current.service_name,
        version=version,
    )
    app.state.settings = current
    app.state.application_state = application_state
    app.state.health = HealthService(state=application_state)
    app.state.container = container
    app.state.catalog = catalog
    app.state.telemetry = telemetry

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        HttpMetricsMiddleware,
        metrics=metrics,
        access_log_health_enabled=current.access_log_health_enabled,
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.include_router(health_router)
    app.include_router(debtors_router)
    if telemetry is not None:
        telemetry.instrument_app(app)
    return app


app = create_app()
