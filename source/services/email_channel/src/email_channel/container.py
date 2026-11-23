"""Composition root сервиса Email Channel."""

import punq

from email_channel.adapters.messaging.connection import RabbitMQConnection
from email_channel.adapters.messaging.consumer import EmailCommandConsumer
from email_channel.adapters.messaging.outbox_relay import OutboxRelay
from email_channel.adapters.messaging.publisher import RabbitMQPublisher
from email_channel.adapters.persistence.database import Database
from email_channel.adapters.persistence.outbox import SqlAlchemyOutboxStore
from email_channel.adapters.persistence.uow import SqlAlchemyUnitOfWorkFactory
from email_channel.adapters.smtp.probe import AsyncioSmtpProbe
from email_channel.adapters.smtp.rate_limit import AsyncioRateLimiter
from email_channel.adapters.smtp.renderer import Jinja2EmailRenderer
from email_channel.adapters.smtp.secrets import EnvSecretsProvider
from email_channel.adapters.smtp.sender import AiosmtplibEmailSender
from email_channel.application.config import ChannelConfigService
from email_channel.application.delivery import EmailDeliveryService
from email_channel.application.templates import EmailTemplateService
from email_channel.config import Settings
from email_channel.domain import EmailAddress, SecretRef, SmtpConfig
from email_channel.infrastructure.clock import SystemClock
from email_channel.infrastructure.metrics import Metrics


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
    probe = AsyncioSmtpProbe()
    config_service = ChannelConfigService(uow_factory=uow_factory, clock=clock, probe=probe)
    template_service = EmailTemplateService(uow_factory=uow_factory, clock=clock)
    renderer = Jinja2EmailRenderer()
    sender = AiosmtplibEmailSender()
    rate_limiter = AsyncioRateLimiter(settings.rate_limit_per_second)
    secrets = EnvSecretsProvider(settings)
    fallback_config = SmtpConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password_ref=SecretRef("SMTP_PASSWORD"),
        from_address=EmailAddress(settings.smtp_from),
        from_name="LoanDebtors",
        use_starttls=settings.smtp_starttls,
        timeout_seconds=settings.smtp_timeout_seconds,
        rate_limit_per_second=settings.rate_limit_per_second,
        enabled=True,
        updated_at=clock.now(),
    )
    delivery = EmailDeliveryService(
        uow_factory=uow_factory,
        clock=clock,
        renderer=renderer,
        sender=sender,
        rate_limiter=rate_limiter,
        secrets=secrets,
        default_locale=settings.email_default_locale,
        fallback_config=fallback_config,
    )
    consumer = EmailCommandConsumer(connection, publisher, delivery, settings, metrics)

    container.register(Database, instance=database)
    container.register(SystemClock, instance=clock)
    container.register(Metrics, instance=metrics)
    container.register(RabbitMQConnection, instance=connection)
    container.register(RabbitMQPublisher, instance=publisher)
    container.register(SqlAlchemyOutboxStore, instance=outbox_store)
    container.register(OutboxRelay, instance=relay)
    container.register(SqlAlchemyUnitOfWorkFactory, instance=uow_factory)
    container.register(ChannelConfigService, instance=config_service)
    container.register(EmailTemplateService, instance=template_service)
    container.register(EmailDeliveryService, instance=delivery)
    container.register(EmailCommandConsumer, instance=consumer)
    return container
