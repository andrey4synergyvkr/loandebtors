"""Кампания рассылки."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from re import fullmatch
from typing import Final

from notifications.domain.enums import CampaignStatus
from notifications.domain.errors import InvalidStateError, ValidationError
from notifications.domain.ids import EMAIL_CHANNEL, CampaignId, Channel, TemplateKey
from notifications.domain.template import (
    MAX_TEMPLATE_KEY_LENGTH,
    TEMPLATE_KEY_PATTERN,
)
from notifications.domain.values import ScheduleSpec, validate_schedule

CAMPAIGN_NAME_MAX_LENGTH: Final = 200
MAX_CRITERIA_KEY_LENGTH: Final = 64
MAX_CRITERIA_VALUE_LENGTH: Final = 255


@dataclass(frozen=True, slots=True)
class DebtorSelection:
    """Параметры выборки должников для АБС.

    Attributes:
        criteria: Параметры выборки для АБС; состав ключей задает контракт АБС.
    """

    criteria: Mapping[str, str]


@dataclass(slots=True)
class Campaign:
    """Агрегат кампании рассылки.

    Attributes:
        id: Идентификатор кампании.
        name: Человекочитаемое имя для оператора.
        channel: Канал рассылки, в v1 всегда email.
        template_key: Выбранный логический шаблон.
        template_version: Зафиксированная версия шаблона.
        status: Текущее состояние жизненного цикла.
        selection: Параметры выгрузки из АБС.
        schedule: None означает немедленный запуск.
        selected_debtors: Сколько должников фактически выгружено.
        selection_expected: Ожидаемое число должников по данным АБС.
        selection_completed_at: Время успешной полной выгрузки.
        messages_created_at: Время создания сообщений после выгрузки.
        created_at: Время создания кампании.
        updated_at: Время последнего изменения.
        scheduled_at: Время постановки в расписание.
        started_at: Время фактического старта.
        finished_at: Время завершения или окончательной остановки.
        cancelled_at: Время отмены оператором.
        failure_reason: Причина статуса FAILED.
    """

    id: CampaignId
    name: str
    channel: Channel
    template_key: TemplateKey
    template_version: int
    status: CampaignStatus
    selection: DebtorSelection
    schedule: ScheduleSpec | None
    selected_debtors: int
    selection_expected: int | None
    selection_completed_at: datetime | None
    messages_created_at: datetime | None
    created_at: datetime
    updated_at: datetime
    scheduled_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    cancelled_at: datetime | None
    failure_reason: str | None

    def ensure_editable(self) -> None:
        """Проверить, что кампания еще не запускалась.

        Raises:
            InvalidStateError: Кампания не в статусе draft.
        """
        if self.status is not CampaignStatus.DRAFT:
            raise InvalidStateError(f"Кампания в статусе {self.status.value} не может быть изменена")

    def schedule_for(self, schedule: ScheduleSpec, now: datetime) -> None:
        """Поставить draft-кампанию в расписание.

        Raises:
            InvalidStateError: Кампания не в статусе draft.
            ValidationError: Правило запуска недопустимо.
        """
        if self.status is not CampaignStatus.DRAFT:
            raise InvalidStateError(f"Кампания в статусе {self.status.value} не может быть запланирована")
        self.schedule = validate_schedule(schedule, now)
        self.status = CampaignStatus.SCHEDULED
        self.scheduled_at = now
        self.updated_at = now

    def cancel(self, now: datetime) -> bool:
        """Отменить запланированную или выполняющуюся кампанию.

        Raises:
            InvalidStateError: Кампания в статусе draft или уже завершена.

        Returns:
            True, если отменена выполняющаяся кампания и нужно отменить сообщения.
        """
        if self.status not in (CampaignStatus.SCHEDULED, CampaignStatus.RUNNING):
            raise InvalidStateError(f"Кампания в статусе {self.status.value} не может быть отменена")
        was_running = self.status is CampaignStatus.RUNNING
        self.status = CampaignStatus.CANCELLED
        self.cancelled_at = now
        self.finished_at = now
        self.updated_at = now
        return was_running

    def mark_running(self, now: datetime) -> bool:
        """Перевести кампанию в running перед выборкой и отправкой.

        Повторный вызов для уже выполняющейся кампании разрешен и нужен для
        повторной доставки campaign.start.

        Raises:
            InvalidStateError: Кампания в терминальном статусе.

        Returns:
            True, если статус изменился.
        """
        if self.status is CampaignStatus.RUNNING:
            return False
        if self.status not in (CampaignStatus.DRAFT, CampaignStatus.SCHEDULED):
            raise InvalidStateError(f"Кампания в статусе {self.status.value} не может быть запущена")
        self.status = CampaignStatus.RUNNING
        self.started_at = now
        self.updated_at = now
        return True

    def mark_messages_created(self, now: datetime) -> None:
        """Зафиксировать завершение создания сообщений.

        Raises:
            InvalidStateError: Кампания не в статусе running.
        """
        if self.status is not CampaignStatus.RUNNING:
            raise InvalidStateError(f"Кампания в статусе {self.status.value} не может создавать сообщения")
        self.messages_created_at = now
        self.updated_at = now

    def fail(self, reason: str, now: datetime) -> None:
        """Перевести кампанию в failed с причиной.

        Raises:
            InvalidStateError: Кампания уже завершена.
        """
        if self.status in (
            CampaignStatus.COMPLETED,
            CampaignStatus.CANCELLED,
            CampaignStatus.FAILED,
        ):
            raise InvalidStateError(
                f"Кампания в статусе {self.status.value} не может быть переведена в failed"
            )
        self.status = CampaignStatus.FAILED
        self.failure_reason = reason[:1000]
        self.finished_at = now
        self.updated_at = now

    def complete(self, now: datetime) -> None:
        """Завершить выполняющуюся кампанию после обработки сообщений.

        Raises:
            InvalidStateError: Кампания не в статусе running.
        """
        if self.status is not CampaignStatus.RUNNING:
            raise InvalidStateError(f"Кампания в статусе {self.status.value} не может быть завершена")
        self.status = CampaignStatus.COMPLETED
        self.finished_at = now
        self.updated_at = now

    def update_details(
        self,
        *,
        name: str,
        template_key: TemplateKey,
        template_version: int,
        selection: DebtorSelection,
        now: datetime,
    ) -> tuple[str, ...]:
        """Обновить редактируемые поля кампании в статусе draft.

        Raises:
            InvalidStateError: Кампания не в статусе draft.
            ValidationError: Поля кампании недопустимы.

        Returns:
            Имена измененных полей; пустой кортеж означает отсутствие изменений.
        """
        self.ensure_editable()
        normalized = _validate_campaign_details(
            name=name,
            channel=self.channel,
            template_key=template_key,
            template_version=template_version,
            selection=selection,
        )
        changed: list[str] = []
        if self.name != normalized.name:
            self.name = normalized.name
            changed.append("name")
        if self.template_key != normalized.template_key:
            self.template_key = normalized.template_key
            changed.append("template_key")
        if self.template_version != normalized.template_version:
            self.template_version = normalized.template_version
            changed.append("template_version")
        if dict(self.selection.criteria) != dict(normalized.selection.criteria):
            self.selection = normalized.selection
            changed.append("selection")
        if changed:
            self.updated_at = now
        return tuple(changed)


@dataclass(frozen=True, slots=True)
class _ValidatedCampaignDetails:
    """Нормализованные и проверенные поля кампании.

    Attributes:
        name: Очищенное имя кампании.
        template_key: Нормализованный ключ шаблона.
        template_version: Проверенный номер версии.
        selection: Проверенная выборка должников.
    """

    name: str
    template_key: TemplateKey
    template_version: int
    selection: DebtorSelection


def _validate_campaign_details(
    *,
    name: str,
    channel: Channel,
    template_key: TemplateKey,
    template_version: int,
    selection: DebtorSelection,
) -> _ValidatedCampaignDetails:
    """Проверить и нормализовать редактируемые поля кампании.

    Raises:
        ValidationError: Имя, канал, шаблон или критерии выборки недопустимы.
    """
    normalized_name = name.strip()
    if not normalized_name or len(normalized_name) > CAMPAIGN_NAME_MAX_LENGTH:
        raise ValidationError(f"Имя кампании должно содержать от 1 до {CAMPAIGN_NAME_MAX_LENGTH} символов")
    if channel != EMAIL_CHANNEL:
        raise ValidationError("В первой версии поддерживается только канал email")
    normalized_key = template_key.strip()
    if not normalized_key or len(normalized_key) > MAX_TEMPLATE_KEY_LENGTH:
        raise ValidationError(f"Ключ шаблона должен содержать от 1 до {MAX_TEMPLATE_KEY_LENGTH} символов")
    if fullmatch(TEMPLATE_KEY_PATTERN, normalized_key) is None:
        raise ValidationError("Ключ шаблона должен соответствовать шаблону ^[a-z][a-z0-9._-]*$")
    if template_version < 1:
        raise ValidationError("Версия шаблона должна быть не меньше 1")
    criteria = dict(selection.criteria)
    for key, value in criteria.items():
        if not key or len(key) > MAX_CRITERIA_KEY_LENGTH:
            raise ValidationError(
                f"Ключ критерия выборки должен содержать от 1 до {MAX_CRITERIA_KEY_LENGTH} символов"
            )
        if len(value) > MAX_CRITERIA_VALUE_LENGTH:
            raise ValidationError(
                f"Значение критерия выборки не может быть длиннее {MAX_CRITERIA_VALUE_LENGTH} символов"
            )
    return _ValidatedCampaignDetails(
        name=normalized_name,
        template_key=TemplateKey(normalized_key),
        template_version=template_version,
        selection=DebtorSelection(criteria=criteria),
    )


def create_campaign(
    *,
    campaign_id: CampaignId,
    name: str,
    channel: Channel,
    template_key: TemplateKey,
    template_version: int,
    selection: DebtorSelection,
    now: datetime,
) -> Campaign:
    """Создать кампанию в статусе draft.

    Raises:
        ValidationError: Поля кампании недопустимы.
    """
    normalized = _validate_campaign_details(
        name=name,
        channel=channel,
        template_key=template_key,
        template_version=template_version,
        selection=selection,
    )
    return Campaign(
        id=campaign_id,
        name=normalized.name,
        channel=channel,
        template_key=normalized.template_key,
        template_version=normalized.template_version,
        status=CampaignStatus.DRAFT,
        selection=normalized.selection,
        schedule=None,
        selected_debtors=0,
        selection_expected=None,
        selection_completed_at=None,
        messages_created_at=None,
        created_at=now,
        updated_at=now,
        scheduled_at=None,
        started_at=None,
        finished_at=None,
        cancelled_at=None,
        failure_reason=None,
    )
