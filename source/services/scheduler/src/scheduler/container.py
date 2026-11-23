"""Composition root сервиса Scheduler."""

import punq

from scheduler.adapters.messaging.connection import RabbitMQConnection
from scheduler.adapters.messaging.consumer import SchedulerCommandConsumer
from scheduler.adapters.messaging.outbox_relay import OutboxRelay
from scheduler.adapters.messaging.publisher import RabbitMQPublisher
from scheduler.adapters.persistence.database import Database
from scheduler.adapters.persistence.outbox import SqlAlchemyOutboxStore
from scheduler.adapters.persistence.uow import SqlAlchemyUnitOfWorkFactory
from scheduler.adapters.scheduling.registrar import APSchedulerJobRegistrar
from scheduler.application.scheduling import (
    CampaignTrigger,
    ScheduleRecovery,
    ScheduleService,
)
from scheduler.config import Settings
from scheduler.infrastructure.clock import SystemClock
from scheduler.infrastructure.metrics import Metrics


def build_container(settings: Settings) -> punq.Container:
    """Собрать контейнер зависимостей сервиса."""
    container = punq.Container()
    container.register(Settings, instance=settings)

    database = Database(settings)
    clock = SystemClock()
    metrics = Metrics()
    connection = RabbitMQConnection(settings)
    publisher = RabbitMQPublisher(connection)
    outbox_store = SqlAlchemyOutboxStore(
        database.session_factory,
        max_attempts=settings.outbox_max_attempts,
        retry_base_seconds=settings.outbox_retry_base_seconds,
        retry_max_seconds=settings.outbox_retry_max_seconds,
    )
    relay = OutboxRelay(
        store=outbox_store,
        publisher=publisher,
        settings=settings,
        metrics=metrics,
        clock=clock,
    )
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    registrar = APSchedulerJobRegistrar(settings)
    trigger = CampaignTrigger(
        uow_factory=uow_factory,
        registrar=registrar,
        clock=clock,
        metrics=metrics,
    )
    schedule_service = ScheduleService(
        uow_factory=uow_factory,
        registrar=registrar,
        clock=clock,
        metrics=metrics,
        trigger=trigger,
        misfire_grace_seconds=settings.schedule_misfire_grace_seconds,
    )
    recovery = ScheduleRecovery(
        uow_factory=uow_factory,
        registrar=registrar,
        trigger=trigger,
        clock=clock,
        metrics=metrics,
    )
    consumer = SchedulerCommandConsumer(
        connection=connection,
        publisher=publisher,
        service=schedule_service,
        settings=settings,
        metrics=metrics,
    )

    container.register(Database, instance=database)
    container.register(SystemClock, instance=clock)
    container.register(Metrics, instance=metrics)
    container.register(RabbitMQConnection, instance=connection)
    container.register(RabbitMQPublisher, instance=publisher)
    container.register(SqlAlchemyOutboxStore, instance=outbox_store)
    container.register(OutboxRelay, instance=relay)
    container.register(SqlAlchemyUnitOfWorkFactory, instance=uow_factory)
    container.register(APSchedulerJobRegistrar, instance=registrar)
    container.register(CampaignTrigger, instance=trigger)
    container.register(ScheduleService, instance=schedule_service)
    container.register(ScheduleRecovery, instance=recovery)
    container.register(SchedulerCommandConsumer, instance=consumer)
    return container
