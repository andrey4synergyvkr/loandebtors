"""Health-проверка PostgreSQL."""

from email_channel.adapters.persistence.database import Database
from email_channel.application.health import (
    DATABASE_CHECK_NAME,
    HealthCheck,
    HealthStatus,
)

DATABASE_READY_DETAIL: str = "PostgreSQL доступен"
DATABASE_UNAVAILABLE_DETAIL: str = "PostgreSQL недоступен"


class DatabaseHealthProbe:
    """Проверяет доступность PostgreSQL простым запросом."""

    name: str = DATABASE_CHECK_NAME

    def __init__(self, database: Database) -> None:
        """Сохранить объект базы данных."""
        self._database = database

    async def check(self) -> HealthCheck:
        """Выполнить запрос и вернуть статус зависимости."""
        try:
            await self._database.check()
        except Exception as exc:
            return HealthCheck(
                name=self.name,
                status=HealthStatus.UNAVAILABLE,
                detail=f"{DATABASE_UNAVAILABLE_DETAIL}: {type(exc).__name__}",
            )
        return HealthCheck(
            name=self.name,
            status=HealthStatus.OK,
            detail=DATABASE_READY_DETAIL,
        )
