"""Подключение к PostgreSQL и фабрика сессий."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from scheduler.config import Settings


class Database:
    """Движок PostgreSQL и фабрика асинхронных сессий."""

    def __init__(self, settings: Settings) -> None:
        """Создать движок и фабрику сессий по настройкам."""
        self._engine = create_async_engine(
            settings.database_url,
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        """Вернуть асинхронный движок SQLAlchemy."""
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Вернуть фабрику асинхронных сессий."""
        return self._session_factory

    async def check(self) -> None:
        """Проверить доступность PostgreSQL простым запросом."""
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        """Закрыть пул соединений."""
        await self._engine.dispose()
