"""Точка входа сервиса Email Channel."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import metadata
from typing import Final

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from email_channel.adapters.http.config import router as config_router
from email_channel.adapters.http.health import router as health_router
from email_channel.adapters.http.middleware import (
    CorrelationIdMiddleware,
    HttpMetricsMiddleware,
)
from email_channel.adapters.http.problems import (
    conflict_exception_handler,
    domain_validation_exception_handler,
    not_found_exception_handler,
    request_validation_exception_handler,
    unhandled_exception_handler,
)
from email_channel.adapters.http.templates import router as templates_router
from email_channel.adapters.messaging.connection import RabbitMQConnection
from email_channel.adapters.messaging.consumer import EmailCommandConsumer
from email_channel.adapters.messaging.health import (
    EmailConsumerHealthProbe,
    OutboxRelayHealthProbe,
    RabbitMQHealthProbe,
)
from email_channel.adapters.messaging.outbox_relay import OutboxRelay
from email_channel.adapters.persistence.database import Database
from email_channel.adapters.persistence.health import DatabaseHealthProbe
from email_channel.application.config import ChannelConfigService
from email_channel.application.health import (
    ApplicationState,
    HealthProbe,
    HealthService,
)
from email_channel.application.templates import EmailTemplateService
from email_channel.config import Settings, get_settings
from email_channel.container import build_container
from email_channel.domain import (
    ConflictError,
    InvalidStateError,
    NotFoundError,
)
from email_channel.domain import ValidationError as DomainValidationError
from email_channel.infrastructure.clock import SystemClock
from email_channel.infrastructure.logging import configure_logging
from email_channel.infrastructure.metrics import Metrics
from email_channel.infrastructure.telemetry import TelemetryRuntime, create_telemetry

PACKAGE_NAME: Final = "loandebtors-email-channel"
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
    consumer: EmailCommandConsumer,
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
        probes.append(
            OutboxRelayHealthProbe(
                relay=relay,
                clock=clock,
                max_age_seconds=settings.outbox_health_max_age_seconds,
            )
        )
        probes.append(EmailConsumerHealthProbe(consumer))
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
    consumer: EmailCommandConsumer = container.resolve(EmailCommandConsumer)

    if settings.check_dependencies or settings.run_background_workers:
        try:
            await connection.start()
        except Exception:
            logger.warning("RabbitMQ недоступен при старте сервиса", exc_info=True)
    if settings.run_background_workers:
        await relay.start()
        await consumer.start()
    health.mark_ready()
    try:
        yield
    finally:
        health.begin_shutdown()
        if settings.run_background_workers:
            await consumer.stop()
            await relay.stop()
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
    consumer: EmailCommandConsumer = container.resolve(EmailCommandConsumer)
    clock: SystemClock = container.resolve(SystemClock)
    metrics: Metrics = container.resolve(Metrics)
    config_service: ChannelConfigService = container.resolve(ChannelConfigService)
    template_service: EmailTemplateService = container.resolve(EmailTemplateService)

    app = FastAPI(
        title="LoanDebtors Email Channel",
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
        probes=_build_health_probes(current, database, connection, relay, consumer, clock),
        timeout_seconds=current.health_check_timeout_seconds,
    )
    app.state.container = container
    app.state.telemetry = telemetry
    app.state.metrics = metrics
    app.state.channel_config_service = config_service
    app.state.email_template_service = template_service

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
    app.include_router(config_router)
    app.include_router(templates_router)
    if telemetry is not None:
        telemetry.instrument_app(app, database.engine)
    return app


app = create_app()
