"""Репозиторий настроек SMTP-адаптера."""

from sqlalchemy.ext.asyncio import AsyncSession

from email_channel.adapters.persistence.models import SmtpConfigRow
from email_channel.domain import EmailAddress, SecretRef, SmtpConfig

CONFIG_ID: int = 1


class SqlAlchemyChannelConfigRepository:
    """Хранит единственную строку настроек в схеме email_channel."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def get(self) -> SmtpConfig | None:
        """Вернуть настройки канала или None."""
        row = await self._session.get(SmtpConfigRow, CONFIG_ID)
        if row is None:
            return None
        return SmtpConfig(
            host=row.host,
            port=row.port,
            username=row.username,
            password_ref=SecretRef(row.password_ref),
            from_address=EmailAddress(row.from_address),
            from_name=row.from_name,
            use_starttls=row.use_starttls,
            timeout_seconds=row.timeout_seconds,
            rate_limit_per_second=row.rate_limit_per_second,
            enabled=row.enabled,
            updated_at=row.updated_at,
        )

    async def save(self, config: SmtpConfig) -> None:
        """Создать или обновить настройки канала."""
        row = await self._session.get(SmtpConfigRow, CONFIG_ID)
        if row is None:
            row = SmtpConfigRow(id=CONFIG_ID)
            self._session.add(row)
        row.host = config.host
        row.port = config.port
        row.username = config.username
        row.password_ref = config.password_ref
        row.from_address = config.from_address
        row.from_name = config.from_name
        row.use_starttls = config.use_starttls
        row.timeout_seconds = config.timeout_seconds
        row.rate_limit_per_second = config.rate_limit_per_second
        row.enabled = config.enabled
        row.updated_at = config.updated_at
