"""Сценарий настройки SMTP-адаптера и записи аудита."""

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from email_channel.domain import (
    CHANNEL_ENTITY_TYPE,
    EMAIL_CHANNEL_SERVICE,
    SMTP_ENTITY_ID,
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditOutcome,
    Channel,
    EmailAddress,
    NotFoundError,
    SecretRef,
    SmtpConfig,
    ValidationError,
    ValidationResult,
)
from email_channel.ports.clock import Clock
from email_channel.ports.probe import SmtpProbe
from email_channel.ports.uow import UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Контекст запроса для audit-события.

    Attributes:
        correlation_id: Идентификатор сценария.
        trace_id: Идентификатор OTel-трейса.
    """

    correlation_id: str
    trace_id: str | None


@dataclass(frozen=True, slots=True)
class UpdateChannelConfigCommand:
    """Параметры сохранения настроек SMTP-адаптера.

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


class ChannelConfigService:
    """Читает и сохраняет настройки канала, фиксируя audit-событие."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        probe: SmtpProbe,
    ) -> None:
        """Сохранить фабрику единиц работы, часы и проверку SMTP."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._probe = probe

    async def get_config(self) -> SmtpConfig:
        """Вернуть настройки канала или ошибку NotFoundError."""
        async with self._uow_factory() as uow:
            config = await uow.config.get()
        if config is None:
            raise NotFoundError("Настройки SMTP-адаптера не заданы")
        return config

    async def update_config(
        self,
        command: UpdateChannelConfigCommand,
        context: RequestContext,
    ) -> SmtpConfig:
        """Сохранить настройки и записать channel.config.updated."""
        _validate(command)
        now = self._clock.now()
        config = SmtpConfig(
            host=command.host,
            port=command.port,
            username=command.username,
            password_ref=SecretRef(command.password_ref),
            from_address=EmailAddress(command.from_address),
            from_name=command.from_name,
            use_starttls=command.use_starttls,
            timeout_seconds=command.timeout_seconds,
            rate_limit_per_second=command.rate_limit_per_second,
            enabled=command.enabled,
            updated_at=now,
        )
        async with self._uow_factory() as uow:
            await uow.config.save(config)
            await uow.audit.add(_audit_event(config, now, context))
            await uow.commit()
        return config

    async def validate_config(self, command: UpdateChannelConfigCommand) -> ValidationResult:
        """Проверить настройки и доступность SMTP без сохранения."""
        errors = _validation_errors(command)
        if not errors:
            probe_error = await self._probe.check(
                command.host,
                command.port,
                command.timeout_seconds,
            )
            if probe_error is not None:
                errors.append(f"SMTP недоступен: {probe_error}")
        return ValidationResult(
            valid=not errors,
            errors=tuple(errors),
            checked_at=self._clock.now(),
        )


def _validate(command: UpdateChannelConfigCommand) -> None:
    """Проверить настройки и выбросить первую ошибку."""
    errors = _validation_errors(command)
    if errors:
        raise ValidationError(errors[0])


def _validation_errors(command: UpdateChannelConfigCommand) -> list[str]:
    """Вернуть список нарушений настроек."""
    errors: list[str] = []
    if not command.host:
        errors.append("host не должен быть пустым")
    if not 1 <= command.port <= 65535:
        errors.append("port должен быть от 1 до 65535")
    if not command.username:
        errors.append("username не должен быть пустым")
    if not command.password_ref:
        errors.append("password_ref не должен быть пустым")
    if not command.from_address:
        errors.append("from_address не должен быть пустым")
    if not command.from_name:
        errors.append("from_name не должен быть пустым")
    if not 1 <= command.timeout_seconds <= 300:
        errors.append("timeout_seconds должен быть от 1 до 300")
    if not 1 <= command.rate_limit_per_second <= 1000:
        errors.append("rate_limit_per_second должен быть от 1 до 1000")
    return errors


def _audit_event(
    config: SmtpConfig,
    occurred_at: datetime,
    context: RequestContext,
) -> AuditEvent:
    """Собрать audit-событие изменения настроек канала."""
    return AuditEvent(
        event_id=AuditEventId(uuid4()),
        occurred_at=occurred_at,
        service=EMAIL_CHANNEL_SERVICE,
        actor=AuditActor(type=AuditActorType.ADMINISTRATOR, identifier=None),
        action=AuditAction.CHANNEL_CONFIG_UPDATED,
        entity_type=CHANNEL_ENTITY_TYPE,
        entity_id=SMTP_ENTITY_ID,
        campaign_id=None,
        message_id=None,
        channel=Channel("email"),
        outcome=AuditOutcome.SUCCESS,
        details={
            "host": config.host,
            "port": str(config.port),
            "use_starttls": str(config.use_starttls).lower(),
            "rate_limit_per_second": str(config.rate_limit_per_second),
            "enabled": str(config.enabled).lower(),
        },
        correlation_id=context.correlation_id or uuid4().hex,
        trace_id=context.trace_id,
    )
