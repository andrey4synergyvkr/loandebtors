"""Точка входа сервиса Notifications."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import metadata
from typing import Final

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from notifications.adapters.abs.source import HttpAbsDebtorSource
from notifications.adapters.http.campaigns import router as campaigns_router
from notifications.adapters.http.health import router as health_router
from notifications.adapters.http.messages import router as messages_router
from notifications.adapters.http.middleware import (
    CorrelationIdMiddleware,
    HttpMetricsMiddleware,
)
from notifications.adapters.http.problems import (
    conflict_exception_handler,
    domain_validation_exception_handler,
    not_found_exception_handler,
    request_validation_exception_handler,
    unhandled_exception_handler,
)
from notifications.adapters.http.templates import router as templates_router
from notifications.adapters.messaging.connection import RabbitMQConnection
from notifications.adapters.messaging.consumer import NotificationCommandConsumer
from notifications.adapters.messaging.health import (
    ConsumerHealthProbe,
    MaintenanceHealthProbe,
    MessageResultConsumerHealthProbe,
    OutboxRelayHealthProbe,
    RabbitMQHealthProbe,
)
from notifications.adapters.messaging.outbox_relay import OutboxRelay
from notifications.adapters.messaging.result_consumer import NotificationResultConsumer
from notifications.adapters.persistence.database import Database
from notifications.adapters.persistence.health import DatabaseHealthProbe
from notifications.application.campaigns import CampaignService
from notifications.application.health import (
    ApplicationState,
    HealthProbe,
    HealthService,
)
from notifications.application.maintenance import MaintenanceWorker
from notifications.application.templates import TemplateService
from notifications.config import Settings, get_settings
from notifications.container import build_container
from notifications.domain import ConflictError, InvalidStateError, NotFoundError
from notifications.domain import ValidationError as DomainValidationError
from notifications.infrastructure.clock import SystemClock
from notifications.infrastructure.logging import configure_logging
from notifications.infrastructure.metrics import Metrics
from notifications.infrastructure.telemetry import TelemetryRuntime, create_telemetry

PACKAGE_NAME: Final = "loandebtors-notifications"
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
    consumer: NotificationCommandConsumer,
    result_consumer: NotificationResultConsumer,
    maintenance: MaintenanceWorker,
    clock: SystemClock,
) -> tuple[HealthProbe, ...]:
    """Собрать проверки зависимостей по настройкам сервиса."""
    if not settings.check_dependencies:
        return ()
    probes: list[HealthProbe] = [
        DatabaseHealthProbe(database),
        RabbitMQHealthProbe(connection),
    ]
    if settings.run_background_workers:
        probes.append(ConsumerHealthProbe(consumer))
        probes.append(MessageResultConsumerHealthProbe(result_consumer))
        probes.append(
            OutboxRelayHealthProbe(
                relay=relay,
                clock=clock,
                max_age_seconds=settings.outbox_health_max_age_seconds,
            )
        )
        probes.append(
            MaintenanceHealthProbe(
                worker=maintenance,
                clock=clock,
                max_age_seconds=settings.maintenance_health_max_age_seconds,
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
    consumer: NotificationCommandConsumer = container.resolve(NotificationCommandConsumer)
    result_consumer: NotificationResultConsumer = container.resolve(NotificationResultConsumer)
    maintenance: MaintenanceWorker = container.resolve(MaintenanceWorker)
    abs_source: HttpAbsDebtorSource = container.resolve(HttpAbsDebtorSource)

    if settings.check_dependencies or settings.run_background_workers:
        try:
            await connection.start()
        except Exception:
            logger.warning("RabbitMQ недоступен при старте сервиса", exc_info=True)
    if settings.run_background_workers:
        await relay.start()
        await consumer.start()
        await result_consumer.start()
        await maintenance.start()
    health.mark_ready()
    try:
        yield
    finally:
        health.begin_shutdown()
        if settings.run_background_workers:
            await maintenance.stop()
            await result_consumer.stop()
            await consumer.stop()
            await relay.stop()
        await abs_source.aclose()
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
    consumer: NotificationCommandConsumer = container.resolve(NotificationCommandConsumer)
    result_consumer: NotificationResultConsumer = container.resolve(NotificationResultConsumer)
    maintenance_worker: MaintenanceWorker = container.resolve(MaintenanceWorker)
    clock: SystemClock = container.resolve(SystemClock)
    metrics: Metrics = container.resolve(Metrics)
    template_service: TemplateService = container.resolve(TemplateService)
    campaign_service: CampaignService = container.resolve(CampaignService)

    app = FastAPI(
        title="LoanDebtors Notifications",
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
            consumer,
            result_consumer,
            maintenance_worker,
            clock,
        ),
        timeout_seconds=current.health_check_timeout_seconds,
    )
    app.state.container = container
    app.state.telemetry = telemetry
    app.state.template_service = template_service
    app.state.campaign_service = campaign_service

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
    app.add_exception_handler(
        ConflictError,
        conflict_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        InvalidStateError,
        conflict_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(health_router)
    app.include_router(campaigns_router)
    app.include_router(messages_router)
    app.include_router(templates_router)
    if telemetry is not None:
        telemetry.instrument_app(app, database.engine)
    return app


app = create_app()
