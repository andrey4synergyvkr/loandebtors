"""Состояние приложения и агрегация health-проверок."""

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Protocol

APPLICATION_CHECK_NAME: Final = "application"
DATABASE_CHECK_NAME: Final = "database"
RABBITMQ_CHECK_NAME: Final = "rabbitmq"
AUDIT_CONSUMER_CHECK_NAME: Final = "audit_consumer"

APPLICATION_READY_DETAIL: Final = "Сервис готов принимать запросы"
APPLICATION_STARTING_DETAIL: Final = "Инициализация не завершена"
APPLICATION_SHUTTING_DOWN_DETAIL: Final = "Сервис останавливается"


class ApplicationPhase(StrEnum):
    """Фаза жизненного цикла приложения.

    Attributes:
        STARTING: Приложение инициализируется.
        READY: Приложение готово принимать запросы.
        SHUTTING_DOWN: Приложение останавливается.
    """

    STARTING = "starting"
    READY = "ready"
    SHUTTING_DOWN = "shutting_down"


class HealthStatus(StrEnum):
    """Статус проверки работоспособности.

    Attributes:
        OK: Проверка пройдена.
        DEGRADED: Сервис работает в ограниченном режиме.
        UNAVAILABLE: Сервис не готов принимать запросы.
    """

    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class HealthCheck:
    """Результат одной проверки.

    Attributes:
        name: Имя проверки.
        status: Статус проверки.
        detail: Пояснение для оператора.
    """

    name: str
    status: HealthStatus
    detail: str | None


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """Снимок состояния сервиса для health-ответа.

    Attributes:
        status: Итоговый статус.
        service: Имя сервиса.
        version: Версия сервиса.
        uptime_seconds: Время работы процесса в секундах.
        checks: Результаты проверок.
    """

    status: HealthStatus
    service: str
    version: str
    uptime_seconds: float
    checks: tuple[HealthCheck, ...]


class HealthProbe(Protocol):
    """Внешняя проверка, которая дополняет состояние приложения."""

    name: str

    async def check(self) -> HealthCheck:
        """Вернуть результат проверки зависимости."""
        ...


@dataclass(slots=True)
class ApplicationState:
    """Состояние приложения и готовность к работе.

    Attributes:
        service: Имя сервиса.
        version: Версия сервиса.
    """

    service: str
    version: str
    _started_monotonic: float = field(default_factory=time.monotonic)
    _phase: ApplicationPhase = ApplicationPhase.STARTING

    def mark_ready(self) -> None:
        """Перевести приложение в фазу готовности."""
        self._phase = ApplicationPhase.READY

    def begin_shutdown(self) -> None:
        """Перевести приложение в фазу остановки."""
        self._phase = ApplicationPhase.SHUTTING_DOWN

    def uptime_seconds(self) -> float:
        """Вернуть время работы процесса в секундах."""
        return max(0.0, time.monotonic() - self._started_monotonic)

    def check(self) -> HealthCheck:
        """Вернуть проверку фазы приложения."""
        if self._phase is ApplicationPhase.READY:
            status = HealthStatus.OK
            detail = APPLICATION_READY_DETAIL
        elif self._phase is ApplicationPhase.STARTING:
            status = HealthStatus.UNAVAILABLE
            detail = APPLICATION_STARTING_DETAIL
        else:
            status = HealthStatus.UNAVAILABLE
            detail = APPLICATION_SHUTTING_DOWN_DETAIL
        return HealthCheck(name=APPLICATION_CHECK_NAME, status=status, detail=detail)

    def snapshot(self) -> HealthSnapshot:
        """Собрать снимок только по состоянию приложения."""
        check = self.check()
        return HealthSnapshot(
            status=check.status,
            service=self.service,
            version=self.version,
            uptime_seconds=self.uptime_seconds(),
            checks=(check,),
        )


class HealthService:
    """Агрегатор состояния приложения и внешних проверок."""

    def __init__(
        self,
        state: ApplicationState,
        probes: tuple[HealthProbe, ...] = (),
        timeout_seconds: float = 3.0,
    ) -> None:
        """Сохранить состояние, проверки и таймаут одной проверки."""
        self._state = state
        self._probes = probes
        self._timeout_seconds = timeout_seconds

    def mark_ready(self) -> None:
        """Перевести приложение в фазу готовности."""
        self._state.mark_ready()

    def begin_shutdown(self) -> None:
        """Перевести приложение в фазу остановки."""
        self._state.begin_shutdown()

    async def snapshot(self) -> HealthSnapshot:
        """Собрать снимок состояния вместе с проверками зависимостей."""
        checks = [self._state.check()]
        for probe in self._probes:
            checks.append(await self._run_probe(probe))
        return HealthSnapshot(
            status=self._aggregate(checks),
            service=self._state.service,
            version=self._state.version,
            uptime_seconds=self._state.uptime_seconds(),
            checks=tuple(checks),
        )

    async def _run_probe(self, probe: HealthProbe) -> HealthCheck:
        """Выполнить проверку с таймаутом и без проброса исключений."""
        try:
            return await asyncio.wait_for(probe.check(), timeout=self._timeout_seconds)
        except TimeoutError:
            return HealthCheck(
                name=probe.name,
                status=HealthStatus.UNAVAILABLE,
                detail=f"Проверка не завершилась за {self._timeout_seconds:.1f} секунд",
            )
        except Exception as exc:  # health не должен падать из-за проверки
            return HealthCheck(
                name=probe.name,
                status=HealthStatus.UNAVAILABLE,
                detail=f"Проверка завершилась ошибкой: {type(exc).__name__}",
            )

    @staticmethod
    def _aggregate(checks: list[HealthCheck]) -> HealthStatus:
        """Свести статусы проверок в итоговый статус."""
        statuses = {check.status for check in checks}
        if HealthStatus.UNAVAILABLE in statuses:
            return HealthStatus.UNAVAILABLE
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        return HealthStatus.OK
