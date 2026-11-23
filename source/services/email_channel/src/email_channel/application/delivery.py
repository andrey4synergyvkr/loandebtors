"""Сценарий отправки email-сообщения."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from email_channel.application.config import RequestContext
from email_channel.domain import (
    EMAIL_CHANNEL_SERVICE,
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditOutcome,
    DeliveryOutcome,
    EmailAddress,
    MessageFailed,
    MessageSent,
    NotificationCommand,
    SecretError,
    SendAttempt,
    SendFailure,
    SendReceipt,
    SmtpConfig,
    TemplateError,
)
from email_channel.ports.clock import Clock
from email_channel.ports.rate_limit import RateLimiter
from email_channel.ports.renderer import EmailRenderer
from email_channel.ports.sender import EmailSender, SecretsProvider
from email_channel.ports.uow import UnitOfWorkFactory

MESSAGE_ENTITY_TYPE = "message"


class DeliveryStatus(StrEnum):
    """Итог обработки message.send.

    Attributes:
        SENT: Провайдер принял письмо.
        FAILED: Отправка завершилась ошибкой, результат опубликован.
        DUPLICATE: Сообщение уже обрабатывалось.
    """

    SENT = "sent"
    FAILED = "failed"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """Результат обработки команды.

    Attributes:
        status: Итоговый статус.
        attempt_number: Номер попытки.
    """

    status: DeliveryStatus
    attempt_number: int


class EmailDeliveryService:
    """Рендерит, отправляет и фиксирует результат в outbox."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        renderer: EmailRenderer,
        sender: EmailSender,
        rate_limiter: RateLimiter,
        secrets: SecretsProvider,
        default_locale: str = "ru-RU",
        fallback_config: SmtpConfig | None = None,
    ) -> None:
        """Сохранить зависимости сценария."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._renderer = renderer
        self._sender = sender
        self._rate_limiter = rate_limiter
        self._secrets = secrets
        self._default_locale = default_locale
        self._fallback_config = fallback_config

    async def handle(
        self,
        command: NotificationCommand,
        context: RequestContext,
    ) -> DeliveryResult:
        """Обработать команду и опубликовать результат."""
        async with self._uow_factory() as uow:
            if await uow.processed.is_processed(command.message_id):
                return DeliveryResult(status=DeliveryStatus.DUPLICATE, attempt_number=0)
            config = await uow.config.get()
            if config is None:
                config = self._fallback_config
            template = await uow.templates.get(
                command.template_key,
                command.template_version,
                self._default_locale,
            )
            attempt_number = await uow.attempts.count_by_message(command.message_id) + 1

        started_at = self._clock.now()
        receipt: SendReceipt | None = None
        failure: SendFailure | None = None
        if config is None:
            failure = SendFailure(
                outcome=DeliveryOutcome.PERMANENT_FAILURE,
                provider_error_code="channel_not_configured",
                provider_error_message="Настройки SMTP-адаптера не заданы",
            )
        elif not config.enabled:
            failure = SendFailure(
                outcome=DeliveryOutcome.PERMANENT_FAILURE,
                provider_error_code="channel_disabled",
                provider_error_message="Канал выключен",
            )
        elif template is None:
            failure = SendFailure(
                outcome=DeliveryOutcome.PERMANENT_FAILURE,
                provider_error_code="template_not_found",
                provider_error_message="Email-шаблон не найден",
            )
        else:
            try:
                rendered = self._renderer.render(
                    template,
                    command.variables,
                    EmailAddress(command.recipient.address),
                )
            except TemplateError as exc:
                failure = SendFailure(
                    outcome=DeliveryOutcome.PERMANENT_FAILURE,
                    provider_error_code="template_error",
                    provider_error_message=str(exc),
                )
            else:
                try:
                    password = await self._secrets.get(config.password_ref)
                except SecretError as exc:
                    failure = SendFailure(
                        outcome=DeliveryOutcome.PERMANENT_FAILURE,
                        provider_error_code="secret_not_found",
                        provider_error_message=str(exc),
                    )
                else:
                    self._rate_limiter.configure(config.rate_limit_per_second)
                    await self._rate_limiter.acquire()
                    result = await self._sender.send(config, rendered, password)
                    if isinstance(result, SendReceipt):
                        receipt = result
                    else:
                        failure = result

        if receipt is None and failure is None:
            failure = SendFailure(
                outcome=DeliveryOutcome.PERMANENT_FAILURE,
                provider_error_code="unknown_error",
                provider_error_message="Отправка не выполнена",
            )

        finished_at = self._clock.now()
        terminal = (
            receipt is not None
            or failure is None
            or failure.outcome
            not in (
                DeliveryOutcome.TRANSIENT_FAILURE,
                DeliveryOutcome.RATE_LIMITED,
            )
        )
        async with self._uow_factory() as uow:
            inserted = True
            if terminal:
                inserted = await uow.processed.mark_processed(command.message_id, finished_at)
            if not inserted:
                return DeliveryResult(
                    status=DeliveryStatus.DUPLICATE,
                    attempt_number=attempt_number,
                )
            if receipt is None:
                assert failure is not None
                attempt_outcome = failure.outcome
            else:
                attempt_outcome = DeliveryOutcome.SENT
            await uow.attempts.add(
                SendAttempt(
                    message_id=command.message_id,
                    attempt_number=attempt_number,
                    recipient=EmailAddress(command.recipient.address),
                    started_at=started_at,
                    finished_at=finished_at,
                    outcome=attempt_outcome,
                    provider_message_id=receipt.provider_message_id if receipt is not None else None,
                    provider_error_code=failure.provider_error_code if failure is not None else None,
                    provider_error_message=(failure.provider_error_message if failure is not None else None),
                )
            )
            if receipt is not None:
                await uow.results.add_sent(
                    MessageSent(
                        message_id=command.message_id,
                        campaign_id=command.campaign_id,
                        channel=command.channel,
                        attempt_number=attempt_number,
                        provider_message_id=receipt.provider_message_id,
                        occurred_at=receipt.accepted_at,
                    ),
                    context.correlation_id,
                    context.trace_id,
                )
                await uow.audit.add(
                    _audit_event(
                        command=command,
                        action=AuditAction.MESSAGE_SENT,
                        outcome=AuditOutcome.SUCCESS,
                        details={
                            "attempt_number": str(attempt_number),
                            "provider_message_id": receipt.provider_message_id or "",
                        },
                        occurred_at=receipt.accepted_at,
                        context=context,
                    )
                )
            else:
                assert failure is not None
                retryable = failure.outcome in (
                    DeliveryOutcome.TRANSIENT_FAILURE,
                    DeliveryOutcome.RATE_LIMITED,
                )
                await uow.results.add_failed(
                    MessageFailed(
                        message_id=command.message_id,
                        campaign_id=command.campaign_id,
                        channel=command.channel,
                        attempt_number=attempt_number,
                        outcome=failure.outcome,
                        retryable=retryable,
                        error_code=failure.provider_error_code,
                        error_message=failure.provider_error_message,
                        occurred_at=finished_at,
                    ),
                    context.correlation_id,
                    context.trace_id,
                )
                await uow.audit.add(
                    _audit_event(
                        command=command,
                        action=AuditAction.MESSAGE_FAILED,
                        outcome=AuditOutcome.FAILURE,
                        details={
                            "attempt_number": str(attempt_number),
                            "outcome": failure.outcome.value,
                            "retryable": str(retryable).lower(),
                            "error_code": failure.provider_error_code or "",
                        },
                        occurred_at=finished_at,
                        context=context,
                    )
                )
            await uow.commit()

        status = DeliveryStatus.SENT if receipt is not None else DeliveryStatus.FAILED
        return DeliveryResult(status=status, attempt_number=attempt_number)

    async def record_consumer_failure(
        self,
        command: NotificationCommand,
        context: RequestContext,
        error_code: str,
        error_message: str,
    ) -> DeliveryResult:
        """Зафиксировать окончательный отказ обработки команды."""
        occurred_at = self._clock.now()
        async with self._uow_factory() as uow:
            if await uow.processed.is_processed(command.message_id):
                return DeliveryResult(status=DeliveryStatus.DUPLICATE, attempt_number=0)
            attempt_number = await uow.attempts.count_by_message(command.message_id) + 1
            inserted = await uow.processed.mark_processed(command.message_id, occurred_at)
            if not inserted:
                return DeliveryResult(
                    status=DeliveryStatus.DUPLICATE,
                    attempt_number=attempt_number,
                )
            await uow.attempts.add(
                SendAttempt(
                    message_id=command.message_id,
                    attempt_number=attempt_number,
                    recipient=EmailAddress(command.recipient.address),
                    started_at=occurred_at,
                    finished_at=occurred_at,
                    outcome=DeliveryOutcome.PERMANENT_FAILURE,
                    provider_message_id=None,
                    provider_error_code=error_code,
                    provider_error_message=error_message,
                )
            )
            await uow.results.add_failed(
                MessageFailed(
                    message_id=command.message_id,
                    campaign_id=command.campaign_id,
                    channel=command.channel,
                    attempt_number=attempt_number,
                    outcome=DeliveryOutcome.PERMANENT_FAILURE,
                    retryable=False,
                    error_code=error_code,
                    error_message=error_message,
                    occurred_at=occurred_at,
                ),
                context.correlation_id,
                context.trace_id,
            )
            await uow.audit.add(
                _audit_event(
                    command=command,
                    action=AuditAction.MESSAGE_FAILED,
                    outcome=AuditOutcome.FAILURE,
                    details={
                        "attempt_number": str(attempt_number),
                        "outcome": DeliveryOutcome.PERMANENT_FAILURE.value,
                        "retryable": "false",
                        "error_code": error_code,
                    },
                    occurred_at=occurred_at,
                    context=context,
                )
            )
            await uow.commit()
        return DeliveryResult(
            status=DeliveryStatus.FAILED,
            attempt_number=attempt_number,
        )


def _audit_event(
    *,
    command: NotificationCommand,
    action: AuditAction,
    outcome: AuditOutcome,
    details: dict[str, str],
    occurred_at: datetime,
    context: RequestContext,
) -> AuditEvent:
    """Собрать audit-событие результата отправки."""
    return AuditEvent(
        event_id=AuditEventId(uuid4()),
        occurred_at=occurred_at,
        service=EMAIL_CHANNEL_SERVICE,
        actor=AuditActor(type=AuditActorType.SYSTEM, identifier=EMAIL_CHANNEL_SERVICE),
        action=action,
        entity_type=MESSAGE_ENTITY_TYPE,
        entity_id=str(command.message_id),
        campaign_id=command.campaign_id,
        message_id=command.message_id,
        channel=command.channel,
        outcome=outcome,
        details=details,
        correlation_id=context.correlation_id or uuid4().hex,
        trace_id=context.trace_id,
    )
