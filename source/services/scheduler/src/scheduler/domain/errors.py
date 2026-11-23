"""Ошибки предметной области Scheduler."""


class DomainError(Exception):
    """Базовое нарушение правил предметной области."""


class ValidationError(DomainError):
    """Недопустимое значение поля."""


class InvalidStateError(DomainError):
    """Действие запрещено текущим статусом."""


class NotFoundError(DomainError):
    """Запрошенный объект отсутствует."""
