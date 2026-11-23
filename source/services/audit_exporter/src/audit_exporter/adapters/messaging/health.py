"""Health-проверки RabbitMQ и консьюмера audit.events."""

from audit_exporter.adapters.messaging.connection import RabbitMQConnection
from audit_exporter.adapters.messaging.consumer import AuditEventConsumer
from audit_exporter.application.health import (
    AUDIT_CONSUMER_CHECK_NAME,
    RABBITMQ_CHECK_NAME,
    HealthCheck,
    HealthStatus,
)

RABBITMQ_READY_DETAIL: str = "Соединение с RabbitMQ установлено"
RABBITMQ_UNAVAILABLE_DETAIL: str = "RabbitMQ недоступен"
AUDIT_CONSUMER_READY_DETAIL: str = "Консьюмер audit.events принимает сообщения"
AUDIT_CONSUMER_NOT_STARTED_DETAIL: str = "Консьюмер audit.events еще не запущен"
AUDIT_CONSUMER_ERROR_DETAIL: str = "Консьюмер audit.events остановлен с ошибкой"


class RabbitMQHealthProbe:
    """Проверяет готовность соединения RabbitMQ."""

    name: str = RABBITMQ_CHECK_NAME

    def __init__(self, connection: RabbitMQConnection) -> None:
        """Сохранить управляемое подключение."""
        self._connection = connection

    async def check(self) -> HealthCheck:
        """Убедиться, что соединение установлено."""
        try:
            await self._connection.start()
            await self._connection.check()
        except Exception as exc:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.UNAVAILABLE,
                detail=f"{RABBITMQ_UNAVAILABLE_DETAIL}: {type(exc).__name__}",
            )
        return HealthCheck(
            name=self.name,
            status=HealthStatus.OK,
            detail=RABBITMQ_READY_DETAIL,
        )


class AuditConsumerHealthProbe:
    """Проверяет, что консьюмер подключён к очереди без ошибок supervisor."""

    name: str = AUDIT_CONSUMER_CHECK_NAME

    def __init__(self, consumer: AuditEventConsumer) -> None:
        """Сохранить консьюмер."""
        self._consumer = consumer

    async def check(self) -> HealthCheck:
        """Вернуть статус фоновой задачи консьюмера."""
        if not self._consumer.is_running:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.UNAVAILABLE,
                detail=AUDIT_CONSUMER_NOT_STARTED_DETAIL,
            )
        if self._consumer.last_error is not None:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.DEGRADED,
                detail=f"{AUDIT_CONSUMER_ERROR_DETAIL}: {self._consumer.last_error}",
            )
        return HealthCheck(
            name=self.name,
            status=HealthStatus.OK,
            detail=AUDIT_CONSUMER_READY_DETAIL,
        )
