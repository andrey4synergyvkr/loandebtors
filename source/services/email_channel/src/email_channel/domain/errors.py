"""Ошибки домена Email Channel."""


class DomainError(Exception):
    """Базовое нарушение правил предметной области."""


class ValidationError(DomainError):
    """Недопустимое значение поля или параметра."""


class NotFoundError(DomainError):
    """Запрошенный объект отсутствует."""


class ConflictError(DomainError):
    """Объект уже существует или изменился конкурентно."""


class InvalidStateError(DomainError):
    """Действие запрещено текущим состоянием объекта."""


class ChannelNotConfiguredError(DomainError):
    """Настройки SMTP-адаптера отсутствуют или канал выключен."""


class TemplateError(DomainError):
    """Шаблон не найден или не может быть отрендерен."""


class SecretError(DomainError):
    """Секрет не найден или недоступен."""
