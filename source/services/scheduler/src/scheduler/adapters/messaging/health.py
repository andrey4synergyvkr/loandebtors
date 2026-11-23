"""Health-проверки RabbitMQ, потребителя и outbox relay."""

from datetime import datetime

from scheduler.adapters.messaging.connection import RabbitMQConnection
from scheduler.adapters.messaging.consumer import SchedulerCommandConsumer
from scheduler.adapters.messaging.outbox_relay import OutboxRelay
from scheduler.application.health import (
    CONSUMER_CHECK_NAME,
    OUTBOX_RELAY_CHECK_NAME,
    RABBITMQ_CHECK_NAME,
    HealthCheck,
    HealthStatus,
)
from scheduler.ports.clock import Clock

RABBITMQ_READY_DETAIL: str = "Соединение с RabbitMQ установлено"
RABBITMQ_UNAVAILABLE_DETAIL: str = "RabbitMQ недоступен"
CONSUMER_READY_DETAIL: str = "Потребитель команд обрабатывает очередь"
CONSUMER_STOPPED_DETAIL: str = "Потребитель команд не запущен"
OUTBOX_RELAY_READY_DETAIL: str = "Outbox relay обрабатывает очередь"
OUTBOX_RELAY_NOT_STARTED_DETAIL: str = "Outbox relay еще не выполнял итерации"
OUTBOX_RELAY_LAG_DETAIL: str = "Outbox relay не выполнял итерации дольше допустимого"


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


class ConsumerHealthProbe:
    """Проверяет, что потребитель команд запущен и не сообщал об ошибках."""

    name: str = CONSUMER_CHECK_NAME

    def __init__(self, consumer: SchedulerCommandConsumer) -> None:
        """Сохранить потребителя команд."""
        self._consumer = consumer

    async def check(self) -> HealthCheck:
        """Вернуть состояние потребителя."""
        if not self._consumer.is_running:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.UNAVAILABLE,
                detail=CONSUMER_STOPPED_DETAIL,
            )
        if self._consumer.last_error is not None:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.DEGRADED,
                detail=f"Последняя ошибка: {self._consumer.last_error}",
            )
        return HealthCheck(
            name=self.name,
            status=HealthStatus.OK,
            detail=CONSUMER_READY_DETAIL,
        )


class OutboxRelayHealthProbe:
    """Проверяет, что outbox relay выполняет итерации без отставания."""

    name: str = OUTBOX_RELAY_CHECK_NAME

    def __init__(
        self,
        relay: OutboxRelay,
        clock: Clock,
        max_age_seconds: float,
    ) -> None:
        """Сохранить relay, часы и допустимый возраст итерации."""
        self._relay = relay
        self._clock = clock
        self._max_age_seconds = max_age_seconds

    async def check(self) -> HealthCheck:
        """Сравнить время последней итерации с допустимым возрастом."""
        last_iteration: datetime | None = self._relay.last_iteration_at
        if last_iteration is None:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.UNAVAILABLE,
                detail=OUTBOX_RELAY_NOT_STARTED_DETAIL,
            )
        age_seconds = (self._clock.now() - last_iteration).total_seconds()
        if age_seconds > self._max_age_seconds:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.DEGRADED,
                detail=f"{OUTBOX_RELAY_LAG_DETAIL}: {age_seconds:.1f} секунд",
            )
        if self._relay.last_error is not None:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.DEGRADED,
                detail=f"Последняя ошибка: {self._relay.last_error}",
            )
        return HealthCheck(
            name=self.name,
            status=HealthStatus.OK,
            detail=OUTBOX_RELAY_READY_DETAIL,
        )
