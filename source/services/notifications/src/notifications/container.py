"""Composition root сервиса Notifications."""

import punq

from notifications.adapters.abs.source import HttpAbsDebtorSource
from notifications.adapters.messaging.connection import RabbitMQConnection
from notifications.adapters.messaging.consumer import NotificationCommandConsumer
from notifications.adapters.messaging.outbox_relay import OutboxRelay
from notifications.adapters.messaging.publisher import RabbitMQPublisher
from notifications.adapters.messaging.result_consumer import NotificationResultConsumer
from notifications.adapters.persistence.database import Database
from notifications.adapters.persistence.outbox import SqlAlchemyOutboxStore
from notifications.adapters.persistence.uow import SqlAlchemyUnitOfWorkFactory
from notifications.application.campaign_start import CampaignStartService
from notifications.application.campaigns import CampaignService
from notifications.application.maintenance import MaintenanceService, MaintenanceWorker
from notifications.application.message_results import MessageResultService
from notifications.application.templates import TemplateService
from notifications.config import Settings
from notifications.infrastructure.clock import SystemClock
from notifications.infrastructure.metrics import Metrics


def build_container(settings: Settings) -> punq.Container:
    """Собрать контейнер инфраструктурных зависимостей."""
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
    template_service = TemplateService(uow_factory=uow_factory, clock=clock)
    campaign_service = CampaignService(uow_factory=uow_factory, clock=clock)
    abs_source = HttpAbsDebtorSource(settings)
    campaign_start_service = CampaignStartService(
        source=abs_source,
        uow_factory=uow_factory,
        clock=clock,
        settings=settings,
        metrics=metrics,
    )
    consumer = NotificationCommandConsumer(
        connection=connection,
        publisher=publisher,
        service=campaign_start_service,
        settings=settings,
        metrics=metrics,
    )
    message_result_service = MessageResultService(
        uow_factory=uow_factory,
        clock=clock,
        settings=settings,
    )
    result_consumer = NotificationResultConsumer(
        connection=connection,
        publisher=publisher,
        service=message_result_service,
        settings=settings,
        metrics=metrics,
    )
    maintenance_service = MaintenanceService(
        uow_factory=uow_factory,
        clock=clock,
        retention_days=settings.retention_days,
        recovery_grace_seconds=settings.recovery_grace_seconds,
        batch_size=settings.maintenance_batch_size,
        outbox_max_attempts=settings.outbox_max_attempts,
        metrics=metrics,
    )
    maintenance_worker = MaintenanceWorker(
        service=maintenance_service,
        interval_seconds=settings.maintenance_interval_seconds,
        clock=clock,
    )

    container.register(Database, instance=database)
    container.register(SystemClock, instance=clock)
    container.register(Metrics, instance=metrics)
    container.register(RabbitMQConnection, instance=connection)
    container.register(RabbitMQPublisher, instance=publisher)
    container.register(SqlAlchemyOutboxStore, instance=outbox_store)
    container.register(OutboxRelay, instance=relay)
    container.register(SqlAlchemyUnitOfWorkFactory, instance=uow_factory)
    container.register(TemplateService, instance=template_service)
    container.register(CampaignService, instance=campaign_service)
    container.register(HttpAbsDebtorSource, instance=abs_source)
    container.register(CampaignStartService, instance=campaign_start_service)
    container.register(NotificationCommandConsumer, instance=consumer)
    container.register(MessageResultService, instance=message_result_service)
    container.register(NotificationResultConsumer, instance=result_consumer)
    container.register(MaintenanceService, instance=maintenance_service)
    container.register(MaintenanceWorker, instance=maintenance_worker)
    return container
