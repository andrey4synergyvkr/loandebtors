"""Проверка сценария отправки email-сообщения."""

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from email_channel.application.config import RequestContext
from email_channel.application.delivery import DeliveryStatus, EmailDeliveryService
from email_channel.domain import (
    AuditAction,
    AuditEvent,
    CampaignId,
    Channel,
    DebtorId,
    DeliveryOutcome,
    EmailAddress,
    EmailTemplate,
    IdempotencyKey,
    MessageFailed,
    MessageId,
    MessageSent,
    NotificationCommand,
    Recipient,
    RenderedEmail,
    SecretRef,
    SendAttempt,
    SendFailure,
    SendReceipt,
    SendResult,
    SmtpConfig,
    TemplateKey,
)
from email_channel.ports import UnitOfWorkFactory

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
_MESSAGE_ID = uuid4()
_CAMPAIGN_ID = uuid4()


class FakeClock:
    """Часы с фиксированным временем."""

    def now(self) -> datetime:
        """Вернуть фиксированное время."""
        return _NOW


class FakeConfigRepository:
    """Настройки канала в памяти."""

    def __init__(self, config: SmtpConfig | None) -> None:
        """Сохранить настройки."""
        self.config = config

    async def get(self) -> SmtpConfig | None:
        """Вернуть настройки."""
        return self.config

    async def save(self, config: SmtpConfig) -> None:
        """Сохранить настройки."""
        self.config = config


class FakeTemplateRepository:
    """Шаблоны в памяти."""

    def __init__(self, template: EmailTemplate | None) -> None:
        """Сохранить шаблон."""
        self.template = template

    async def get(
        self,
        key: TemplateKey,
        version: int,
        locale: str | None = None,
    ) -> EmailTemplate | None:
        """Вернуть шаблон."""
        return self.template

    async def list(self, *args: object, **kwargs: object) -> tuple[tuple[EmailTemplate, ...], int]:
        """Вернуть пустую страницу."""
        return (), 0

    async def save(self, template: EmailTemplate) -> None:
        """Сохранить шаблон."""
        self.template = template


class FakeAttempts:
    """Попытки отправки в памяти."""

    def __init__(self) -> None:
        """Создать пустой список."""
        self.attempts: list[SendAttempt] = []

    async def add(self, attempt: SendAttempt) -> None:
        """Запомнить попытку."""
        self.attempts.append(attempt)

    async def count_by_message(self, message_id: MessageId) -> int:
        """Вернуть число попыток."""
        return len(self.attempts)


class FakeProcessed:
    """Идемпотентность в памяти."""

    def __init__(self, processed: bool = False) -> None:
        """Сохранить начальное состояние."""
        self.processed = processed

    async def is_processed(self, message_id: MessageId) -> bool:
        """Вернуть состояние обработки."""
        return self.processed

    async def mark_processed(self, message_id: MessageId, processed_at: datetime) -> bool:
        """Отметить сообщение обработанным."""
        if self.processed:
            return False
        self.processed = True
        return True


class FakeResults:
    """Результаты отправки в памяти."""

    def __init__(self) -> None:
        """Создать пустые списки."""
        self.sent: list[MessageSent] = []
        self.failed: list[MessageFailed] = []

    async def add_sent(
        self,
        event: MessageSent,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Запомнить успех."""
        self.sent.append(event)

    async def add_failed(
        self,
        event: MessageFailed,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Запомнить ошибку."""
        self.failed.append(event)


class FakeAudit:
    """Audit-события в памяти."""

    def __init__(self) -> None:
        """Создать пустой список."""
        self.events: list[AuditEvent] = []

    async def add(self, event: AuditEvent) -> None:
        """Запомнить событие."""
        self.events.append(event)


class FakeUnitOfWork:
    """Единица работы с фейковыми репозиториями."""

    def __init__(
        self,
        config: FakeConfigRepository,
        templates: FakeTemplateRepository,
        attempts: FakeAttempts,
        processed: FakeProcessed,
        results: FakeResults,
        audit: FakeAudit,
    ) -> None:
        """Сохранить репозитории."""
        self.config = config
        self.templates = templates
        self.attempts = attempts
        self.processed = processed
        self.results = results
        self.audit = audit
        self.committed = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        """Открыть единицу работы."""
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Закрыть единицу работы."""
        return None

    async def commit(self) -> None:
        """Зафиксировать изменения."""
        self.committed = True


class FakeFactory:
    """Фабрика единицы работы."""

    def __init__(self, uow: FakeUnitOfWork) -> None:
        """Сохранить единицу работы."""
        self.uow = uow

    def __call__(self) -> FakeUnitOfWork:
        """Вернуть единицу работы."""
        return self.uow


class FakeRenderer:
    """Рендерер с заданным результатом."""

    def render(
        self,
        template: EmailTemplate,
        variables: object,
        recipient: EmailAddress,
    ) -> RenderedEmail:
        """Вернуть готовое письмо."""
        return RenderedEmail(
            recipient=recipient,
            subject="Тема",
            html_body="<p>Текст</p>",
            plain_text_body="Текст",
        )


class FakeSender:
    """Отправитель с заданным результатом."""

    def __init__(self, result: SendResult) -> None:
        """Сохранить результат."""
        self.result = result
        self.calls = 0

    async def send(
        self,
        config: SmtpConfig,
        email: RenderedEmail,
        password: str,
    ) -> SendResult:
        """Вернуть результат."""
        self.calls += 1
        return self.result


class FakeRateLimiter:
    """Ограничитель без задержек."""

    def configure(self, rate_per_second: int) -> None:
        """Применить лимит."""
        return None

    async def acquire(self) -> None:
        """Пропустить ожидание."""
        return None


class FakeSecrets:
    """Провайдер секретов."""

    async def get(self, ref: SecretRef) -> str:
        """Вернуть пароль."""
        return "password"


def _config(enabled: bool = True) -> SmtpConfig:
    return SmtpConfig(
        host="smtp.example.com",
        port=587,
        username="user",
        password_ref=SecretRef("SMTP_PASSWORD"),
        from_address=EmailAddress("noreply@example.com"),
        from_name="Bank",
        use_starttls=True,
        timeout_seconds=30.0,
        rate_limit_per_second=10,
        enabled=enabled,
        updated_at=_NOW,
    )


def _template() -> EmailTemplate:
    return EmailTemplate(
        key=TemplateKey("payment-reminder"),
        version=1,
        locale="ru-RU",
        subject_template="Тема",
        html_template="<p>Текст</p>",
        plain_text_template="Текст",
        required_variables=(),
        updated_at=_NOW,
    )


def _command() -> NotificationCommand:
    return NotificationCommand(
        message_id=MessageId(_MESSAGE_ID),
        campaign_id=CampaignId(_CAMPAIGN_ID),
        debtor_id=DebtorId("ABS-1"),
        channel=Channel("email"),
        template_key=TemplateKey("payment-reminder"),
        template_version=1,
        variables={"name": "Иван"},
        recipient=Recipient(channel=Channel("email"), address="debtor@example.com"),
        idempotency_key=IdempotencyKey("idem-1"),
    )


def _service(
    result: SendResult,
    *,
    config: SmtpConfig | None,
    template: EmailTemplate | None,
    processed: bool = False,
) -> tuple[EmailDeliveryService, FakeUnitOfWork, FakeSender]:
    config_repo = FakeConfigRepository(config)
    template_repo = FakeTemplateRepository(template)
    attempts = FakeAttempts()
    processed_repo = FakeProcessed(processed)
    results = FakeResults()
    audit = FakeAudit()
    uow = FakeUnitOfWork(config_repo, template_repo, attempts, processed_repo, results, audit)
    sender = FakeSender(result)
    service = EmailDeliveryService(
        uow_factory=cast(UnitOfWorkFactory, FakeFactory(uow)),
        clock=FakeClock(),
        renderer=FakeRenderer(),
        sender=sender,
        rate_limiter=FakeRateLimiter(),
        secrets=FakeSecrets(),
        default_locale="ru-RU",
    )
    return service, uow, sender


async def test_sent_message_writes_result_and_audit() -> None:
    """Успешная отправка пишет message.sent и audit MESSAGE_SENT."""
    service, uow, sender = _service(
        SendReceipt(provider_message_id="provider-1", accepted_at=_NOW),
        config=_config(),
        template=_template(),
    )

    result = await service.handle(_command(), RequestContext("corr", "trace"))

    assert result.status is DeliveryStatus.SENT
    assert result.attempt_number == 1
    assert sender.calls == 1
    assert uow.committed is True
    assert len(uow.attempts.attempts) == 1
    assert len(uow.results.sent) == 1
    assert uow.results.failed == []
    assert uow.results.sent[0].provider_message_id == "provider-1"
    assert uow.audit.events[0].action is AuditAction.MESSAGE_SENT


async def test_permanent_failure_writes_failed_result_and_audit() -> None:
    """Постоянная ошибка пишет message.failed с retryable false."""
    service, uow, _ = _service(
        SendFailure(
            outcome=DeliveryOutcome.PERMANENT_FAILURE,
            provider_error_code="550",
            provider_error_message="mailbox unavailable",
        ),
        config=_config(),
        template=_template(),
    )

    result = await service.handle(_command(), RequestContext("corr", None))

    assert result.status is DeliveryStatus.FAILED
    assert len(uow.results.failed) == 1
    assert uow.results.sent == []
    assert uow.results.failed[0].retryable is False
    assert uow.results.failed[0].error_code == "550"
    assert uow.audit.events[0].action is AuditAction.MESSAGE_FAILED


async def test_transient_failure_is_retryable() -> None:
    """Временная ошибка помечается retryable true."""
    service, uow, _ = _service(
        SendFailure(
            outcome=DeliveryOutcome.TRANSIENT_FAILURE,
            provider_error_code="421",
            provider_error_message="try later",
        ),
        config=_config(),
        template=_template(),
    )

    await service.handle(_command(), RequestContext("corr", None))

    assert uow.results.failed[0].retryable is True
    assert uow.processed.processed is False


async def test_transient_failure_allows_same_message_retry() -> None:
    """Повтор message.send после временной ошибки снова доходит до SMTP."""
    service, uow, sender = _service(
        SendFailure(
            outcome=DeliveryOutcome.TRANSIENT_FAILURE,
            provider_error_code="421",
            provider_error_message="try later",
        ),
        config=_config(),
        template=_template(),
    )

    first = await service.handle(_command(), RequestContext("corr", None))
    second = await service.handle(_command(), RequestContext("corr", None))

    assert first.status is DeliveryStatus.FAILED
    assert second.status is DeliveryStatus.FAILED
    assert sender.calls == 2
    assert [attempt.attempt_number for attempt in uow.attempts.attempts] == [1, 2]
    assert len(uow.results.failed) == 2


async def test_duplicate_message_is_not_sent() -> None:
    """Повторно доставленная команда не отправляется."""
    service, uow, sender = _service(
        SendReceipt(provider_message_id="provider-1", accepted_at=_NOW),
        config=_config(),
        template=_template(),
        processed=True,
    )

    result = await service.handle(_command(), RequestContext("corr", None))

    assert result.status is DeliveryStatus.DUPLICATE
    assert sender.calls == 0
    assert uow.attempts.attempts == []


async def test_missing_config_is_permanent_failure() -> None:
    """Без настроек канала результат permanent failure без SMTP."""
    service, uow, sender = _service(
        SendReceipt(provider_message_id=None, accepted_at=_NOW),
        config=None,
        template=_template(),
    )

    result = await service.handle(_command(), RequestContext("corr", None))

    assert result.status is DeliveryStatus.FAILED
    assert sender.calls == 0
    assert uow.results.failed[0].error_code == "channel_not_configured"
    assert uow.attempts.attempts


async def test_disabled_channel_is_permanent_failure() -> None:
    """Выключенный канал не отправляет письма."""
    service, uow, sender = _service(
        SendReceipt(provider_message_id=None, accepted_at=_NOW),
        config=_config(enabled=False),
        template=_template(),
    )

    await service.handle(_command(), RequestContext("corr", None))

    assert sender.calls == 0
    assert uow.results.failed[0].error_code == "channel_disabled"
