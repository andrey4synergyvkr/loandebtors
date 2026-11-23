"""Pydantic-схемы HTTP API Notifications."""

from datetime import datetime
from re import fullmatch
from typing import Final, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from notifications.application.campaigns import CampaignPage, MessagePage
from notifications.application.templates import TemplatePage
from notifications.domain import (
    Campaign,
    CampaignStatus,
    DebtorSelection,
    MessageStatus,
    NotificationMessage,
    NotificationTemplate,
    ScheduleKind,
    ScheduleSpec,
    TemplateStatus,
)
from notifications.domain.campaign import CAMPAIGN_NAME_MAX_LENGTH
from notifications.domain.template import (
    MAX_DESCRIPTION_LENGTH,
    MAX_TEMPLATE_KEY_LENGTH,
    MAX_VARIABLE_NAME_LENGTH,
    TEMPLATE_KEY_PATTERN,
    VARIABLE_NAME_PATTERN,
)

CHANNEL_PATTERN: Final = r"^[a-z][a-z0-9_-]*$"
MAX_CHANNEL_LENGTH: Final = 32


class TemplateResponse(BaseModel):
    """Версия логического шаблона в ответе API.

    Attributes:
        key: Логический ключ шаблона.
        version: Номер версии.
        description: Назначение шаблона.
        required_variables: Обязательные переменные рендеринга.
        status: Статус версии.
        created_at: Время создания версии.
        updated_at: Время последнего изменения.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    version: int
    description: str
    required_variables: list[str]
    status: TemplateStatus
    created_at: datetime
    updated_at: datetime


class TemplateListResponse(BaseModel):
    """Страница версий шаблонов в ответе API.

    Attributes:
        items: Версии текущей страницы.
        total: Общее число версий с учётом фильтра.
        limit: Размер страницы.
        offset: Смещение.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[TemplateResponse]
    total: int
    limit: int
    offset: int


class CreateTemplateRequest(BaseModel):
    """Запрос создания версии логического шаблона.

    Attributes:
        key: Логический ключ шаблона.
        version: Номер версии.
        description: Назначение шаблона.
        required_variables: Обязательные переменные рендеринга.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        min_length=1,
        max_length=MAX_TEMPLATE_KEY_LENGTH,
        pattern=TEMPLATE_KEY_PATTERN,
    )
    version: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    required_variables: list[str]

    @field_validator("required_variables")
    @classmethod
    def validate_required_variables(cls, value: list[str]) -> list[str]:
        """Проверить уникальность и формат имён переменных.

        Raises:
            ValueError: Переменные повторяются или не соответствуют формату.
        """
        if len(set(value)) != len(value):
            raise ValueError("Переменные шаблона не должны повторяться")
        for variable in value:
            if not variable or len(variable) > MAX_VARIABLE_NAME_LENGTH:
                raise ValueError(
                    f"Имя переменной должно содержать от 1 до {MAX_VARIABLE_NAME_LENGTH} символов"
                )
            if fullmatch(VARIABLE_NAME_PATTERN, variable) is None:
                raise ValueError("Имя переменной должно соответствовать шаблону ^[a-z][a-z0-9_]*$")
        return value


class UpdateTemplateStatusRequest(BaseModel):
    """Запрос изменения статуса версии шаблона.

    Attributes:
        status: Новый статус версии.
    """

    model_config = ConfigDict(extra="forbid")

    status: TemplateStatus


def template_to_response(template: NotificationTemplate) -> TemplateResponse:
    """Преобразовать доменный шаблон в схему ответа."""
    return TemplateResponse(
        key=template.key,
        version=template.version,
        description=template.description,
        required_variables=list(template.required_variables),
        status=template.status,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def template_page_to_response(page: TemplatePage) -> TemplateListResponse:
    """Преобразовать страницу шаблонов в схему ответа."""
    return TemplateListResponse(
        items=[template_to_response(template) for template in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


class DebtorSelectionSchema(BaseModel):
    """Параметры выборки должников.

    Attributes:
        criteria: Критерии выборки для АБС.
    """

    model_config = ConfigDict(extra="forbid")

    criteria: dict[str, str]


class ScheduleSpecSchema(BaseModel):
    """Правило запуска кампании.

    Attributes:
        kind: Вид расписания.
        timezone: Часовой пояс IANA.
        run_at: Время разового запуска.
        cron: Выражение cron для повторяющегося запуска.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ScheduleKind
    timezone: str
    run_at: datetime | None = None
    cron: str | None = None


class CampaignResponse(BaseModel):
    """Кампания в ответе API.

    Attributes:
        id: Идентификатор кампании.
        name: Имя кампании.
        channel: Канал рассылки.
        template_key: Логический ключ шаблона.
        template_version: Версия шаблона.
        status: Статус кампании.
        selection: Параметры выборки.
        schedule: Правило запуска или None.
        selected_debtors: Число выгруженных должников.
        selection_expected: Ожидаемое число должников.
        selection_completed_at: Время полной выгрузки.
        created_at: Время создания.
        updated_at: Время последнего изменения.
        scheduled_at: Время постановки в расписание.
        started_at: Время старта.
        finished_at: Время завершения.
        cancelled_at: Время отмены.
        failure_reason: Причина ошибки.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    channel: str
    template_key: str
    template_version: int
    status: CampaignStatus
    selection: DebtorSelectionSchema
    schedule: ScheduleSpecSchema | None = None
    selected_debtors: int
    selection_expected: int | None = None
    selection_completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancelled_at: datetime | None = None
    failure_reason: str | None = None


class CampaignListResponse(BaseModel):
    """Страница кампаний в ответе API.

    Attributes:
        items: Кампании текущей страницы.
        total: Общее число кампаний с учётом фильтра.
        limit: Размер страницы.
        offset: Смещение.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[CampaignResponse]
    total: int
    limit: int
    offset: int


class CreateCampaignRequest(BaseModel):
    """Запрос создания кампании.

    Attributes:
        name: Имя кампании.
        channel: Канал рассылки.
        template_key: Логический ключ шаблона.
        template_version: Версия шаблона.
        selection: Параметры выборки.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=CAMPAIGN_NAME_MAX_LENGTH)
    channel: str = Field(pattern=CHANNEL_PATTERN, max_length=MAX_CHANNEL_LENGTH)
    template_key: str = Field(
        min_length=1,
        max_length=MAX_TEMPLATE_KEY_LENGTH,
        pattern=TEMPLATE_KEY_PATTERN,
    )
    template_version: int = Field(ge=1)
    selection: DebtorSelectionSchema


class UpdateCampaignRequest(BaseModel):
    """Запрос изменения кампании в статусе draft.

    Attributes:
        name: Новое имя кампании.
        template_key: Новый ключ шаблона.
        template_version: Новая версия шаблона.
        selection: Новые параметры выборки.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=CAMPAIGN_NAME_MAX_LENGTH)
    template_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_TEMPLATE_KEY_LENGTH,
        pattern=TEMPLATE_KEY_PATTERN,
    )
    template_version: int | None = Field(default=None, ge=1)
    selection: DebtorSelectionSchema | None = None

    @model_validator(mode="after")
    def require_any_field(self) -> Self:
        """Проверить, что передан хотя бы один изменяемый параметр.

        Raises:
            ValueError: Все поля запроса пусты.
        """
        if (
            self.name is None
            and self.template_key is None
            and self.template_version is None
            and self.selection is None
        ):
            raise ValueError("Нужно передать хотя бы одно поле для изменения")
        return self


class ScheduleCampaignRequest(BaseModel):
    """Запрос постановки кампании в расписание.

    Attributes:
        schedule: Правило разового или повторяющегося запуска.
    """

    model_config = ConfigDict(extra="forbid")

    schedule: ScheduleSpecSchema


def schedule_to_schema(schedule: ScheduleSpec | None) -> ScheduleSpecSchema | None:
    """Преобразовать правило запуска в схему ответа."""
    if schedule is None:
        return None
    return ScheduleSpecSchema(
        kind=schedule.kind,
        timezone=schedule.timezone,
        run_at=schedule.run_at,
        cron=schedule.cron,
    )


def campaign_to_response(campaign: Campaign) -> CampaignResponse:
    """Преобразовать доменную кампанию в схему ответа."""
    return CampaignResponse(
        id=campaign.id,
        name=campaign.name,
        channel=campaign.channel,
        template_key=campaign.template_key,
        template_version=campaign.template_version,
        status=campaign.status,
        selection=DebtorSelectionSchema(criteria=dict(campaign.selection.criteria)),
        schedule=schedule_to_schema(campaign.schedule),
        selected_debtors=campaign.selected_debtors,
        selection_expected=campaign.selection_expected,
        selection_completed_at=campaign.selection_completed_at,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
        scheduled_at=campaign.scheduled_at,
        started_at=campaign.started_at,
        finished_at=campaign.finished_at,
        cancelled_at=campaign.cancelled_at,
        failure_reason=campaign.failure_reason,
    )


def campaign_page_to_response(page: CampaignPage) -> CampaignListResponse:
    """Преобразовать страницу кампаний в схему ответа."""
    return CampaignListResponse(
        items=[campaign_to_response(campaign) for campaign in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def selection_from_schema(selection: DebtorSelectionSchema) -> DebtorSelection:
    """Преобразовать параметры выборки в доменное значение."""
    return DebtorSelection(criteria=dict(selection.criteria))


def schedule_from_schema(schedule: ScheduleSpecSchema) -> ScheduleSpec:
    """Преобразовать правило запуска в доменное значение."""
    return ScheduleSpec(
        kind=schedule.kind,
        timezone=schedule.timezone,
        run_at=schedule.run_at,
        cron=schedule.cron,
    )


class MessageRecipientSchema(BaseModel):
    """Получатель сообщения в ответе API.

    Attributes:
        channel: Канал доставки.
        address: Адрес в формате канала.
    """

    model_config = ConfigDict(extra="forbid")

    channel: str
    address: str


class MessageResponse(BaseModel):
    """Сообщение кампании в ответе API.

    Attributes:
        id: Идентификатор сообщения.
        campaign_id: Идентификатор кампании.
        debtor_id: Идентификатор должника.
        channel: Канал доставки.
        template_key: Логический шаблон.
        template_version: Версия шаблона.
        variables: Переменные рендеринга.
        recipient: Получатель сообщения.
        status: Статус сообщения.
        attempt_count: Число завершенных попыток.
        max_attempts: Предел попыток.
        created_at: Время создания.
        queued_at: Время первой публикации.
        last_attempt_at: Время последней попытки.
        sent_at: Время успешной отправки.
        failed_at: Время окончательного отказа.
        next_attempt_at: Время следующей попытки.
        last_error_code: Последний код ошибки.
        last_error_message: Последнее описание ошибки.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    campaign_id: UUID
    debtor_id: str
    channel: str
    template_key: str
    template_version: int
    variables: dict[str, str]
    recipient: MessageRecipientSchema
    status: MessageStatus
    attempt_count: int
    max_attempts: int
    created_at: datetime
    queued_at: datetime | None = None
    last_attempt_at: datetime | None = None
    sent_at: datetime | None = None
    failed_at: datetime | None = None
    next_attempt_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None


class MessageListResponse(BaseModel):
    """Страница сообщений в ответе API.

    Attributes:
        items: Сообщения текущей страницы.
        total: Общее число сообщений с учётом фильтра.
        limit: Размер страницы.
        offset: Смещение.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[MessageResponse]
    total: int
    limit: int
    offset: int


def message_to_response(message: NotificationMessage) -> MessageResponse:
    """Преобразовать доменное сообщение в схему ответа."""
    return MessageResponse(
        id=message.id,
        campaign_id=message.campaign_id,
        debtor_id=message.debtor_id,
        channel=message.channel,
        template_key=message.template_key,
        template_version=message.template_version,
        variables=dict(message.variables),
        recipient=MessageRecipientSchema(
            channel=message.recipient.channel,
            address=message.recipient.address,
        ),
        status=message.status,
        attempt_count=message.attempt_count,
        max_attempts=message.max_attempts,
        created_at=message.created_at,
        queued_at=message.queued_at,
        last_attempt_at=message.last_attempt_at,
        sent_at=message.sent_at,
        failed_at=message.failed_at,
        next_attempt_at=message.next_attempt_at,
        last_error_code=message.last_error_code,
        last_error_message=message.last_error_message,
    )


def message_page_to_response(page: MessagePage) -> MessageListResponse:
    """Преобразовать страницу сообщений в схему ответа."""
    return MessageListResponse(
        items=[message_to_response(message) for message in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
