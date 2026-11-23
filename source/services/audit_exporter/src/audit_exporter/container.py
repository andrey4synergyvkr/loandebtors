"""Composition root сервиса Audit Exporter."""

import punq

from audit_exporter.adapters.messaging.connection import RabbitMQConnection
from audit_exporter.adapters.messaging.consumer import AuditEventConsumer
from audit_exporter.adapters.messaging.publisher import RabbitMQPublisher
from audit_exporter.adapters.messaging.queue_metrics import QueueMetricsCollector
from audit_exporter.adapters.persistence.audit_store import SqlAlchemyAuditStore
from audit_exporter.adapters.persistence.database import Database
from audit_exporter.application.audit_ingest import AuditIngestService
from audit_exporter.application.audit_reader import AuditReader
from audit_exporter.config import Settings
from audit_exporter.infrastructure.clock import SystemClock
from audit_exporter.infrastructure.metrics import Metrics


def build_container(settings: Settings) -> punq.Container:
    """Собрать контейнер инфраструктурных зависимостей."""
    container = punq.Container()
    container.register(Settings, instance=settings)

    database = Database(settings)
    clock = SystemClock()
    metrics = Metrics()
    connection = RabbitMQConnection(settings)
    publisher = RabbitMQPublisher(connection)
    store = SqlAlchemyAuditStore(database.session_factory, clock)
    ingest = AuditIngestService(store)
    reader = AuditReader(store, clock)
    consumer = AuditEventConsumer(connection, publisher, ingest, settings, metrics)
    queue_metrics = QueueMetricsCollector(
        connection,
        consumer,
        metrics,
        settings.queue_metrics_poll_interval_seconds,
    )

    container.register(Database, instance=database)
    container.register(SystemClock, instance=clock)
    container.register(Metrics, instance=metrics)
    container.register(RabbitMQConnection, instance=connection)
    container.register(RabbitMQPublisher, instance=publisher)
    container.register(SqlAlchemyAuditStore, instance=store)
    container.register(AuditIngestService, instance=ingest)
    container.register(AuditReader, instance=reader)
    container.register(AuditEventConsumer, instance=consumer)
    container.register(QueueMetricsCollector, instance=queue_metrics)
    return container
