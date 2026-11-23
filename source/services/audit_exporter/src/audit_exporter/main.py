"""Точка входа сервиса Audit Exporter."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import metadata
from typing import Final

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from audit_exporter.adapters.http.health import router as health_router
from audit_exporter.adapters.http.middleware import (
    CorrelationIdMiddleware,
    HttpMetricsMiddleware,
)
from audit_exporter.adapters.http.problems import (
    domain_validation_exception_handler,
    not_found_exception_handler,
    request_validation_exception_handler,
    unhandled_exception_handler,
)
from audit_exporter.adapters.http.records import router as records_router
from audit_exporter.adapters.messaging.connection import RabbitMQConnection
from audit_exporter.adapters.messaging.consumer import AuditEventConsumer
from audit_exporter.adapters.messaging.health import (
    AuditConsumerHealthProbe,
    RabbitMQHealthProbe,
)
from audit_exporter.adapters.messaging.queue_metrics import QueueMetricsCollector
from audit_exporter.adapters.persistence.database import Database
from audit_exporter.adapters.persistence.health import DatabaseHealthProbe
from audit_exporter.application.audit_reader import AuditReader
from audit_exporter.application.health import (
    ApplicationState,
    HealthProbe,
    HealthService,
)
from audit_exporter.config import Settings, get_settings
from audit_exporter.container import build_container
from audit_exporter.domain import NotFoundError
from audit_exporter.domain import ValidationError as DomainValidationError
from audit_exporter.infrastructure.logging import configure_logging
from audit_exporter.infrastructure.metrics import Metrics
from audit_exporter.infrastructure.telemetry import TelemetryRuntime, create_telemetry

PACKAGE_NAME: Final = "loandebtors-audit-exporter"
_UNKNOWN_VERSION: Final = "unknown"

logger = logging.getLogger(__name__)


def _resolve_version() -> str:
    """Вернуть версию установленного пакета или unknown."""
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return _UNKNOWN_VERSION


def _build_health_probes(
    settings: Settings,
    database: Database,
    connection: RabbitMQConnection,
    consumer: AuditEventConsumer,
) -> tuple[HealthProbe, ...]:
    """Собрать проверки зависимостей по настройкам сервиса."""
    if not settings.check_dependencies:
        return ()
    probes: list[HealthProbe] = [
        DatabaseHealthProbe(database),
        RabbitMQHealthProbe(connection),
    ]
    if settings.run_background_workers:
        probes.append(AuditConsumerHealthProbe(consumer))
    return tuple(probes)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Поднять и корректно освободить ресурсы сервиса."""
    settings: Settings = app.state.settings
    health: HealthService = app.state.health
    container = app.state.container
    database: Database = container.resolve(Database)
    connection: RabbitMQConnection = container.resolve(RabbitMQConnection)
    consumer: AuditEventConsumer = container.resolve(AuditEventConsumer)
    queue_metrics: QueueMetricsCollector = container.resolve(QueueMetricsCollector)

    if settings.check_dependencies or settings.run_background_workers:
        try:
            await connection.start()
        except Exception:
            logger.warning("RabbitMQ недоступен при старте сервиса", exc_info=True)
    if settings.run_background_workers:
        await consumer.start()
        await queue_metrics.start()
    health.mark_ready()
    try:
        yield
    finally:
        health.begin_shutdown()
        if settings.run_background_workers:
            await queue_metrics.stop()
            await consumer.stop()
        await connection.close()
        await database.dispose()
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
    database: Database = container.resolve(Database)
    connection: RabbitMQConnection = container.resolve(RabbitMQConnection)
    consumer: AuditEventConsumer = container.resolve(AuditEventConsumer)
    metrics: Metrics = container.resolve(Metrics)
    reader: AuditReader = container.resolve(AuditReader)

    app = FastAPI(
        title="LoanDebtors Audit Exporter",
        version=version,
        lifespan=lifespan,
    )
    application_state = ApplicationState(
        service=current.service_name,
        version=version,
    )
    app.state.settings = current
    app.state.application_state = application_state
    app.state.health = HealthService(
        state=application_state,
        probes=_build_health_probes(current, database, connection, consumer),
        timeout_seconds=current.health_check_timeout_seconds,
    )
    app.state.container = container
    app.state.telemetry = telemetry
    app.state.metrics = metrics
    app.state.audit_reader = reader

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        HttpMetricsMiddleware,
        metrics=metrics,
        access_log_health_enabled=current.access_log_health_enabled,
    )
    app.add_exception_handler(
        RequestValidationError,
        request_validation_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        DomainValidationError,
        domain_validation_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        NotFoundError,
        not_found_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(health_router)
    app.include_router(records_router)
    if telemetry is not None:
        telemetry.instrument_app(app, database.engine)
    return app


app = create_app()
