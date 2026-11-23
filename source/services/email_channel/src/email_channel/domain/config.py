"""Настройки SMTP-адаптера."""

from dataclasses import dataclass
from datetime import datetime

from email_channel.domain.ids import EmailAddress, SecretRef


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    """Настройки SMTP-адаптера без значения пароля.

    Attributes:
        host: SMTP-хост провайдера.
        port: Порт SMTP.
        username: Учетная запись провайдера.
        password_ref: Ссылка на секрет, сам пароль в домене не хранится.
        from_address: Адрес отправителя.
        from_name: Отображаемое имя отправителя.
        use_starttls: Включает STARTTLS перед отправкой.
        timeout_seconds: Таймаут SMTP-операции.
        rate_limit_per_second: Глобальный лимит писем в секунду.
        enabled: Выключенный канал не принимает новые отправки.
        updated_at: Время последнего изменения настроек.
    """

    host: str
    port: int
    username: str
    password_ref: SecretRef
    from_address: EmailAddress
    from_name: str
    use_starttls: bool
    timeout_seconds: float
    rate_limit_per_second: int
    enabled: bool
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Результат проверки настроек канала.

    Attributes:
        valid: Настройки прошли проверку.
        errors: Список ошибок.
        checked_at: Время проверки.
    """

    valid: bool
    errors: tuple[str, ...]
    checked_at: datetime
