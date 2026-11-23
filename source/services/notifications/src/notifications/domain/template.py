"""Логический шаблон уведомления."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from re import fullmatch
from typing import Final

from notifications.domain.enums import TemplateStatus
from notifications.domain.errors import InvalidStateError, ValidationError
from notifications.domain.ids import TemplateKey

TEMPLATE_KEY_PATTERN: Final = r"^[a-z][a-z0-9._-]*$"
VARIABLE_NAME_PATTERN: Final = r"^[a-z][a-z0-9_]*$"
MAX_TEMPLATE_KEY_LENGTH: Final = 100
MAX_DESCRIPTION_LENGTH: Final = 2000
MAX_VARIABLE_NAME_LENGTH: Final = 64

ALLOWED_STATUS_TRANSITIONS: Final[dict[TemplateStatus, frozenset[TemplateStatus]]] = {
    TemplateStatus.DRAFT: frozenset({TemplateStatus.ACTIVE, TemplateStatus.ARCHIVED}),
    TemplateStatus.ACTIVE: frozenset({TemplateStatus.ARCHIVED}),
    TemplateStatus.ARCHIVED: frozenset(),
}


@dataclass(slots=True)
class NotificationTemplate:
    """Канально-нейтральный шаблон уведомления.

    Attributes:
        key: Логический ключ, общий для всех каналов.
        version: Версия логического шаблона.
        description: Назначение шаблона для оператора.
        required_variables: Переменные, без которых рендеринг невозможен.
        status: Доступность для новых кампаний.
        created_at: Время создания версии.
        updated_at: Время последнего изменения.
    """

    key: TemplateKey
    version: int
    description: str
    required_variables: tuple[str, ...]
    status: TemplateStatus
    created_at: datetime
    updated_at: datetime

    def change_status(self, status: TemplateStatus, now: datetime) -> bool:
        """Сменить статус версии по правилам жизненного цикла.

        Повтор текущего статуса считается успешным и не меняет время изменения.

        Raises:
            InvalidStateError: Переход из текущего статуса запрещён.

        Returns:
            True, если статус изменился.
        """
        if status is self.status:
            return False
        allowed = ALLOWED_STATUS_TRANSITIONS[self.status]
        if status not in allowed:
            raise InvalidStateError(
                f"Переход шаблона из статуса {self.status.value} в {status.value} запрещён"
            )
        self.status = status
        self.updated_at = now
        return True


def create_template(
    *,
    key: str,
    version: int,
    description: str,
    required_variables: Iterable[str],
    now: datetime,
) -> NotificationTemplate:
    """Создать версию логического шаблона после проверки полей.

    Raises:
        ValidationError: Ключ, версия, описание или переменные недопустимы.
    """
    normalized_key = key.strip()
    if not normalized_key or len(normalized_key) > MAX_TEMPLATE_KEY_LENGTH:
        raise ValidationError(f"Ключ шаблона должен содержать от 1 до {MAX_TEMPLATE_KEY_LENGTH} символов")
    if fullmatch(TEMPLATE_KEY_PATTERN, normalized_key) is None:
        raise ValidationError("Ключ шаблона должен соответствовать шаблону ^[a-z][a-z0-9._-]*$")
    if version < 1:
        raise ValidationError("Версия шаблона должна быть не меньше 1")
    normalized_description = description.strip()
    if not normalized_description:
        raise ValidationError("Описание шаблона не может быть пустым")
    if len(normalized_description) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(f"Описание шаблона не может быть длиннее {MAX_DESCRIPTION_LENGTH} символов")
    variables = tuple(required_variables)
    if len(set(variables)) != len(variables):
        raise ValidationError("Переменные шаблона не должны повторяться")
    for variable in variables:
        if not variable or len(variable) > MAX_VARIABLE_NAME_LENGTH:
            raise ValidationError(
                f"Имя переменной должно содержать от 1 до {MAX_VARIABLE_NAME_LENGTH} символов"
            )
        if fullmatch(VARIABLE_NAME_PATTERN, variable) is None:
            raise ValidationError("Имя переменной должно соответствовать шаблону ^[a-z][a-z0-9_]*$")
    return NotificationTemplate(
        key=TemplateKey(normalized_key),
        version=version,
        description=normalized_description,
        required_variables=variables,
        status=TemplateStatus.DRAFT,
        created_at=now,
        updated_at=now,
    )
