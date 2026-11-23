"""Health-проверка планировщика заданий."""

from scheduler.adapters.scheduling.registrar import APSchedulerJobRegistrar
from scheduler.application.health import SCHEDULER_CHECK_NAME, HealthCheck, HealthStatus
from scheduler.application.scheduling import ScheduleRecovery

SCHEDULER_READY_DETAIL: str = "Планировщик заданий запущен"
SCHEDULER_STOPPED_DETAIL: str = "Планировщик заданий не запущен"
SCHEDULER_RECOVERY_ERROR_DETAIL: str = "Восстановление заданий завершилось ошибкой"


class SchedulerHealthProbe:
    """Проверяет, что планировщик запущен и задания восстановлены."""

    name: str = SCHEDULER_CHECK_NAME

    def __init__(self, registrar: APSchedulerJobRegistrar, recovery: ScheduleRecovery) -> None:
        """Сохранить планировщик и сценарий восстановления."""
        self._registrar = registrar
        self._recovery = recovery

    async def check(self) -> HealthCheck:
        """Вернуть состояние планировщика."""
        if not self._registrar.is_running:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.UNAVAILABLE,
                detail=SCHEDULER_STOPPED_DETAIL,
            )
        if self._recovery.last_error is not None:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.DEGRADED,
                detail=f"{SCHEDULER_RECOVERY_ERROR_DETAIL}: {self._recovery.last_error}",
            )
        return HealthCheck(
            name=self.name,
            status=HealthStatus.OK,
            detail=SCHEDULER_READY_DETAIL,
        )
