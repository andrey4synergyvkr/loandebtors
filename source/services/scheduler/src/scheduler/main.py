"""Точка входа сервиса Scheduler."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import metadata
from typing import Final

from fastapi import FastAPI

from scheduler.adapters.http.health import router as health_router
from scheduler.adapters.http.middleware import (
    CorrelationIdMiddleware,
    HttpMetricsMiddleware,
)
from scheduler.adapters.http.problems import unhandled_exception_handler
from scheduler.adapters.messaging.connection import RabbitMQConnection
from scheduler.adapters.messaging.consumer import SchedulerCommandConsumer
from scheduler.adapters.messaging.health import (
    ConsumerHealthProbe,
    OutboxRelayHealthProbe,
    RabbitMQHealthProbe,
)
from scheduler.adapters.messaging.outbox_relay import OutboxRelay
from scheduler.adapters.persistence.database import Database
from scheduler.adapters.persistence.health import DatabaseHealthProbe
from scheduler.adapters.scheduling.health import SchedulerHealthProbe
from scheduler.adapters.scheduling.registrar import APSchedulerJobRegistrar
from scheduler.application.health import (
    ApplicationState,
    HealthProbe,
    HealthService,
)
from scheduler.application.scheduling import ScheduleRecovery
from scheduler.config import Settings, get_settings
from scheduler.container import build_container
from scheduler.infrastructure.clock import SystemClock
from scheduler.infrastructure.logging import configure_logging
from scheduler.infrastructure.metrics import Metrics
from scheduler.infrastructure.telemetry import TelemetryRuntime, create_telemetry

PACKAGE_NAME: Final = "loandebtors-scheduler"
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
    relay: OutboxRelay,
    clock: SystemClock,
    registrar: APSchedulerJobRegistrar,
    recovery: ScheduleRecovery,
    consumer: SchedulerCommandConsumer,
) -> tuple[HealthProbe, ...]:
    """Собрать проверки зависимостей по настройкам сервиса."""
    if not settings.check_dependencies:
        return ()
    probes: list[HealthProbe] = [
        DatabaseHealthProbe(database),
        RabbitMQHealthProbe(connection),
    ]
    if settings.run_background_workers:
        probes.extend(
            (
                SchedulerHealthProbe(registrar, recovery),
                ConsumerHealthProbe(consumer),
                OutboxRelayHealthProbe(
                    relay=relay,
                    clock=clock,
                    max_age_seconds=settings.outbox_health_max_age_seconds,
                ),
            )
        )
    return tuple(probes)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Поднять и корректно освободить ресурсы сервиса."""
    settings: Settings = app.state.settings
    health: HealthService = app.state.health
    container = app.state.container
    database: Database = container.resolve(Database)
    connection: RabbitMQConnection = container.resolve(RabbitMQConnection)
    relay: OutboxRelay = container.resolve(OutboxRelay)
    registrar: APSchedulerJobRegistrar = container.resolve(APSchedulerJobRegistrar)
    recovery: ScheduleRecovery = container.resolve(ScheduleRecovery)
    consumer: SchedulerCommandConsumer = container.resolve(SchedulerCommandConsumer)

    if settings.check_dependencies or settings.run_background_workers:
        try:
            await connection.start()
        except Exception:
            logger.warning("RabbitMQ недоступен при старте сервиса", exc_info=True)
    if settings.run_background_workers:
        registrar.start()
        try:
            await recovery.run()
        except Exception:
            logger.warning("Не удалось восстановить задания планировщика", exc_info=True)
        try:
            await consumer.start()
        except Exception:
            logger.warning("Потребитель команд не запущен", exc_info=True)
        await relay.start()
    health.mark_ready()
    try:
        yield
    finally:
        health.begin_shutdown()
        if settings.run_background_workers:
            await consumer.stop()
            await relay.stop()
            registrar.stop()
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
    relay: OutboxRelay = container.resolve(OutboxRelay)
    clock: SystemClock = container.resolve(SystemClock)
    metrics: Metrics = container.resolve(Metrics)
    registrar: APSchedulerJobRegistrar = container.resolve(APSchedulerJobRegistrar)
    recovery: ScheduleRecovery = container.resolve(ScheduleRecovery)
    consumer: SchedulerCommandConsumer = container.resolve(SchedulerCommandConsumer)

    app = FastAPI(
        title="LoanDebtors Scheduler",
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
        probes=_build_health_probes(
            current,
            database,
            connection,
            relay,
            clock,
            registrar,
            recovery,
            consumer,
        ),
        timeout_seconds=current.health_check_timeout_seconds,
    )
    app.state.container = container
    app.state.telemetry = telemetry

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        HttpMetricsMiddleware,
        metrics=metrics,
        access_log_health_enabled=current.access_log_health_enabled,
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(health_router)
    if telemetry is not None:
        telemetry.instrument_app(app, database.engine)
    return app


app = create_app()
