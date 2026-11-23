"""Health-проверки RabbitMQ и outbox relay."""

from datetime import datetime

from notifications.adapters.messaging.connection import RabbitMQConnection
from notifications.adapters.messaging.consumer import NotificationCommandConsumer
from notifications.adapters.messaging.outbox_relay import OutboxRelay
from notifications.adapters.messaging.result_consumer import NotificationResultConsumer
from notifications.application.health import (
    CAMPAIGN_CONSUMER_CHECK_NAME,
    MAINTENANCE_CHECK_NAME,
    MESSAGE_RESULT_CONSUMER_CHECK_NAME,
    OUTBOX_RELAY_CHECK_NAME,
    RABBITMQ_CHECK_NAME,
    HealthCheck,
    HealthStatus,
)
from notifications.application.maintenance import MaintenanceWorker
from notifications.ports.clock import Clock

RABBITMQ_READY_DETAIL: str = "Соединение с RabbitMQ установлено"
RABBITMQ_UNAVAILABLE_DETAIL: str = "RabbitMQ недоступен"
CONSUMER_READY_DETAIL: str = "Потребитель campaign.start обрабатывает очередь"
CONSUMER_STOPPED_DETAIL: str = "Потребитель campaign.start не запущен"
RESULT_CONSUMER_READY_DETAIL: str = "Потребитель результатов обрабатывает очередь"
RESULT_CONSUMER_STOPPED_DETAIL: str = "Потребитель результатов не запущен"
OUTBOX_RELAY_READY_DETAIL: str = "Outbox relay обрабатывает очередь"
OUTBOX_RELAY_NOT_STARTED_DETAIL: str = "Outbox relay еще не выполнял итерации"
OUTBOX_RELAY_LAG_DETAIL: str = "Outbox relay не выполнял итерации дольше допустимого"
MAINTENANCE_READY_DETAIL: str = "Обслуживание выполняет итерации"
MAINTENANCE_NOT_STARTED_DETAIL: str = "Обслуживание еще не выполняло успешных итераций"
MAINTENANCE_LAG_DETAIL: str = "Обслуживание не выполняло успешных итераций дольше допустимого"
MAINTENANCE_STOPPED_DETAIL: str = "Фоновая задача обслуживания не запущена"


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

    name: str = CAMPAIGN_CONSUMER_CHECK_NAME

    def __init__(self, consumer: NotificationCommandConsumer) -> None:
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


class MessageResultConsumerHealthProbe:
    """Проверяет, что потребитель результатов запущен и не сообщал об ошибках."""

    name: str = MESSAGE_RESULT_CONSUMER_CHECK_NAME

    def __init__(self, consumer: NotificationResultConsumer) -> None:
        """Сохранить потребителя результатов."""
        self._consumer = consumer

    async def check(self) -> HealthCheck:
        """Вернуть состояние потребителя."""
        if not self._consumer.is_running:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.UNAVAILABLE,
                detail=RESULT_CONSUMER_STOPPED_DETAIL,
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
            detail=RESULT_CONSUMER_READY_DETAIL,
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


class MaintenanceHealthProbe:
    """Проверяет, что обслуживание выполняет успешные итерации."""

    name: str = MAINTENANCE_CHECK_NAME

    def __init__(
        self,
        worker: MaintenanceWorker,
        clock: Clock,
        max_age_seconds: float,
    ) -> None:
        """Сохранить worker, часы и допустимый возраст итерации."""
        self._worker = worker
        self._clock = clock
        self._max_age_seconds = max_age_seconds

    async def check(self) -> HealthCheck:
        """Сравнить последнюю успешную итерацию с допустимым возрастом."""
        if not self._worker.is_running:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.UNAVAILABLE,
                detail=MAINTENANCE_STOPPED_DETAIL,
            )
        last_success = self._worker.last_success_at
        if last_success is None:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.UNAVAILABLE,
                detail=MAINTENANCE_NOT_STARTED_DETAIL,
            )
        age_seconds = (self._clock.now() - last_success).total_seconds()
        if age_seconds > self._max_age_seconds:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.DEGRADED,
                detail=f"{MAINTENANCE_LAG_DETAIL}: {age_seconds:.1f} секунд",
            )
        if self._worker.last_error is not None:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.DEGRADED,
                detail=f"Последняя ошибка: {self._worker.last_error}",
            )
        return HealthCheck(
            name=self.name,
            status=HealthStatus.OK,
            detail=MAINTENANCE_READY_DETAIL,
        )
