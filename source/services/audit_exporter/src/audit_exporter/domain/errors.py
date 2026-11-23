"""Ошибки домена сервиса Audit Exporter."""


class DomainError(Exception):
    """Базовое нарушение правил предметной области."""


class ValidationError(DomainError):
    """Недопустимое значение поля или параметра."""


class NotFoundError(DomainError):
    """Запрошенный объект отсутствует."""


class ConflictError(DomainError):
    """Событие с таким идентификатором уже записано с другим содержимым."""
