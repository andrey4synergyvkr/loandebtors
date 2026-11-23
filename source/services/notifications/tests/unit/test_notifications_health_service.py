"""Проверка агрегации health-проверок."""

import asyncio
from collections.abc import Sequence

from notifications.application.health import (
    ApplicationState,
    HealthCheck,
    HealthProbe,
    HealthService,
    HealthStatus,
)


class StaticProbe:
    """Проверка с заранее заданным результатом."""

    def __init__(self, name: str, status: HealthStatus, detail: str | None = None) -> None:
        """Сохранить имя, статус и пояснение."""
        self.name = name
        self._status = status
        self._detail = detail

    async def check(self) -> HealthCheck:
        """Вернуть заранее заданный результат."""
        return HealthCheck(name=self.name, status=self._status, detail=self._detail)


class SlowProbe:
    """Проверка, которая не успевает завершиться."""

    name = "slow"

    async def check(self) -> HealthCheck:
        """Ждать дольше таймаута health service."""
        await asyncio.sleep(0.05)
        return HealthCheck(name=self.name, status=HealthStatus.OK, detail=None)


def _service(probes: Sequence[HealthProbe], timeout: float = 1.0) -> HealthService:
    """Собрать готовый HealthService с проверками."""
    state = ApplicationState(service="notifications", version="0.1.0")
    state.mark_ready()
    return HealthService(state=state, probes=tuple(probes), timeout_seconds=timeout)


async def test_all_probes_ok() -> None:
    """Все успешные проверки дают общий статус ok."""
    service = _service([StaticProbe("database", HealthStatus.OK), StaticProbe("rabbitmq", HealthStatus.OK)])

    snapshot = await service.snapshot()

    assert snapshot.status is HealthStatus.OK
    assert len(snapshot.checks) == 3
    assert snapshot.checks[0].name == "application"


async def test_degraded_probe_gives_degraded_status() -> None:
    """Одна деградация переводит итоговый статус в degraded."""
    service = _service([StaticProbe("outbox_relay", HealthStatus.DEGRADED, "отставание")])

    snapshot = await service.snapshot()

    assert snapshot.status is HealthStatus.DEGRADED


async def test_unavailable_probe_wins_over_degraded() -> None:
    """Недоступная зависимость важнее деградации."""
    service = _service(
        [
            StaticProbe("outbox_relay", HealthStatus.DEGRADED),
            StaticProbe("database", HealthStatus.UNAVAILABLE),
        ]
    )

    snapshot = await service.snapshot()

    assert snapshot.status is HealthStatus.UNAVAILABLE


async def test_slow_probe_becomes_unavailable() -> None:
    """Проверка дольше таймаута становится unavailable."""
    service = _service([SlowProbe()], timeout=0.01)

    snapshot = await service.snapshot()

    assert snapshot.status is HealthStatus.UNAVAILABLE
    assert snapshot.checks[-1].name == "slow"
    assert snapshot.checks[-1].status is HealthStatus.UNAVAILABLE
    assert "не завершилась" in (snapshot.checks[-1].detail or "")
