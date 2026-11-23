"""Схемы Admin Channel API."""

from datetime import datetime
from re import fullmatch

from pydantic import BaseModel, ConfigDict, Field, field_validator

from email_channel.application.templates import (
    LOCALE_PATTERN,
    VARIABLE_PATTERN,
    TemplatePage,
)
from email_channel.domain import EmailTemplate, SmtpConfig, ValidationResult

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
SECRET_REF_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"


class SmtpConfigRequest(BaseModel):
    """Запрос сохранения настроек SMTP-адаптера.

    Attributes:
        host: SMTP-хост провайдера.
        port: Порт SMTP.
        username: Учетная запись провайдера.
        password_ref: Ссылка на секрет.
        from_address: Адрес отправителя.
        from_name: Отображаемое имя отправителя.
        use_starttls: Включает STARTTLS.
        timeout_seconds: Таймаут SMTP-операции.
        rate_limit_per_second: Глобальный лимит писем в секунду.
        enabled: Выключенный канал не принимает новые отправки.
    """

    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password_ref: str = Field(pattern=SECRET_REF_PATTERN)
    from_address: str = Field(pattern=EMAIL_PATTERN, max_length=320)
    from_name: str = Field(min_length=1, max_length=200)
    use_starttls: bool
    timeout_seconds: float = Field(ge=1, le=300)
    rate_limit_per_second: int = Field(ge=1, le=1000)
    enabled: bool


class SmtpConfigResponse(BaseModel):
    """Ответ с настройками SMTP-адаптера.

    Attributes:
        host: SMTP-хост провайдера.
        port: Порт SMTP.
        username: Учетная запись провайдера.
        password_ref: Ссылка на секрет.
        from_address: Адрес отправителя.
        from_name: Отображаемое имя отправителя.
        use_starttls: Включает STARTTLS.
        timeout_seconds: Таймаут SMTP-операции.
        rate_limit_per_second: Глобальный лимит писем в секунду.
        enabled: Выключенный канал не принимает новые отправки.
        updated_at: Время последнего изменения.
    """

    model_config = ConfigDict(extra="forbid")

    host: str
    port: int
    username: str
    password_ref: str
    from_address: str
    from_name: str
    use_starttls: bool
    timeout_seconds: float
    rate_limit_per_second: int
    enabled: bool
    updated_at: datetime


def config_to_response(config: SmtpConfig) -> SmtpConfigResponse:
    """Преобразовать доменные настройки в схему ответа."""
    return SmtpConfigResponse(
        host=config.host,
        port=config.port,
        username=config.username,
        password_ref=config.password_ref,
        from_address=config.from_address,
        from_name=config.from_name,
        use_starttls=config.use_starttls,
        timeout_seconds=config.timeout_seconds,
        rate_limit_per_second=config.rate_limit_per_second,
        enabled=config.enabled,
        updated_at=config.updated_at,
    )


class ValidationResultResponse(BaseModel):
    """Результат проверки настроек.

    Attributes:
        valid: Настройки прошли проверку.
        errors: Список ошибок.
        checked_at: Время проверки.
    """

    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str]
    checked_at: datetime


def validation_to_response(result: ValidationResult) -> ValidationResultResponse:
    """Преобразовать результат проверки в схему ответа."""
    return ValidationResultResponse(
        valid=result.valid,
        errors=list(result.errors),
        checked_at=result.checked_at,
    )


class EmailTemplateRequest(BaseModel):
    """Запрос сохранения email-шаблона.

    Attributes:
        locale: Язык и регион.
        subject_template: Jinja2-шаблон темы.
        html_template: Jinja2-шаблон HTML-части.
        plain_text_template: Jinja2-шаблон текстовой части.
        required_variables: Обязательные переменные.
    """

    model_config = ConfigDict(extra="forbid")

    locale: str = Field(pattern=LOCALE_PATTERN, max_length=10)
    subject_template: str = Field(min_length=1)
    html_template: str = Field(min_length=1)
    plain_text_template: str = Field(min_length=1)
    required_variables: list[str]

    @field_validator("required_variables")
    @classmethod
    def validate_variables(cls, value: list[str]) -> list[str]:
        """Проверить уникальность и формат имён переменных.

        Raises:
            ValueError: Переменные повторяются или не соответствуют формату.
        """
        if len(set(value)) != len(value):
            raise ValueError("Переменные шаблона не должны повторяться")
        for variable in value:
            if fullmatch(VARIABLE_PATTERN, variable) is None:
                raise ValueError("Имя переменной должно соответствовать шаблону ^[a-z][a-z0-9_]*$")
        return value


class EmailTemplateResponse(BaseModel):
    """Email-шаблон в ответе API.

    Attributes:
        key: Логический ключ шаблона.
        version: Версия канального варианта.
        locale: Язык и регион.
        subject_template: Jinja2-шаблон темы.
        html_template: Jinja2-шаблон HTML-части.
        plain_text_template: Jinja2-шаблон текстовой части.
        required_variables: Обязательные переменные.
        updated_at: Время последнего изменения.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    version: int
    locale: str
    subject_template: str
    html_template: str
    plain_text_template: str
    required_variables: list[str]
    updated_at: datetime


class EmailTemplateListResponse(BaseModel):
    """Страница email-шаблонов.

    Attributes:
        items: Шаблоны текущей страницы.
        total: Общее число шаблонов.
        limit: Размер страницы.
        offset: Смещение.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[EmailTemplateResponse]
    total: int
    limit: int
    offset: int


def template_to_response(template: EmailTemplate) -> EmailTemplateResponse:
    """Преобразовать доменный шаблон в схему ответа."""
    return EmailTemplateResponse(
        key=template.key,
        version=template.version,
        locale=template.locale,
        subject_template=template.subject_template,
        html_template=template.html_template,
        plain_text_template=template.plain_text_template,
        required_variables=list(template.required_variables),
        updated_at=template.updated_at,
    )


def template_page_to_response(page: TemplatePage) -> EmailTemplateListResponse:
    """Преобразовать страницу шаблонов в схему ответа."""
    return EmailTemplateListResponse(
        items=[template_to_response(template) for template in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
