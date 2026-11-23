"""Сообщение кампании и результат попытки."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from notifications.domain.enums import MessageStatus
from notifications.domain.ids import (
    CampaignId,
    Channel,
    DebtorId,
    IdempotencyKey,
    MessageId,
    TemplateKey,
)
from notifications.domain.values import DeliveryOutcome, Recipient


@dataclass(slots=True)
class NotificationMessage:
    """Сообщение, созданное для должника в рамках кампании.

    Attributes:
        id: Идентификатор сообщения и ключ дедупликации.
        campaign_id: Кампания-владелец.
        debtor_id: Должник-получатель.
        channel: Канал доставки.
        template_key: Логический шаблон.
        template_version: Версия шаблона на момент создания сообщения.
        variables: Снимок переменных для повторной отправки.
        recipient: Снимок получателя на момент создания.
        idempotency_key: Защита от дубля campaign + debtor + channel.
        status: Текущее состояние.
        attempt_count: Количество завершенных попыток.
        max_attempts: Предел попыток для этого сообщения.
        created_at: Время создания сообщения.
        queued_at: Время первой публикации в message.send.
        last_attempt_at: Время последней попытки.
        sent_at: Время успешного ответа провайдера.
        failed_at: Время окончательного отказа.
        next_attempt_at: Плановое время следующей попытки.
        last_error_code: Последний код ошибки провайдера.
        last_error_message: Последнее описание ошибки без персональных данных.
    """

    id: MessageId
    campaign_id: CampaignId
    debtor_id: DebtorId
    channel: Channel
    template_key: TemplateKey
    template_version: int
    variables: Mapping[str, str]
    recipient: Recipient
    idempotency_key: IdempotencyKey
    status: MessageStatus
    attempt_count: int
    max_attempts: int
    created_at: datetime
    queued_at: datetime | None
    last_attempt_at: datetime | None
    sent_at: datetime | None
    failed_at: datetime | None
    next_attempt_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None

    def mark_sent(
        self,
        *,
        attempt_number: int,
        occurred_at: datetime,
    ) -> bool:
        """Отметить успешную отправку сообщения.

        Returns:
            False, если сообщение уже в терминальном статусе.
        """
        if self.status in TERMINAL_MESSAGE_STATUSES:
            return False
        self.attempt_count = max(self.attempt_count, attempt_number)
        self.last_attempt_at = occurred_at
        self.sent_at = occurred_at
        self.status = MessageStatus.SENT
        self.next_attempt_at = None
        self.last_error_code = None
        self.last_error_message = None
        return True

    def mark_failed(
        self,
        *,
        attempt_number: int,
        occurred_at: datetime,
        error_code: str | None,
        error_message: str | None,
        retry_at: datetime | None,
    ) -> bool:
        """Отметить неуспешную попытку и при необходимости запланировать повтор.

        Returns:
            False, если сообщение уже в терминальном статусе.
        """
        if self.status in TERMINAL_MESSAGE_STATUSES:
            return False
        self.attempt_count = max(self.attempt_count, attempt_number)
        self.last_attempt_at = occurred_at
        self.last_error_code = error_code
        self.last_error_message = error_message[:1000] if error_message else None
        if retry_at is not None:
            self.status = MessageStatus.QUEUED
            self.next_attempt_at = retry_at
            return True
        self.status = MessageStatus.FAILED
        self.failed_at = occurred_at
        self.next_attempt_at = None
        return True

    def mark_requeued(self) -> None:
        """Зафиксировать передачу сообщения в outbox без смены статуса."""
        if self.status is MessageStatus.QUEUED:
            self.next_attempt_at = None

    def cancel_if_pending(self) -> bool:
        """Отменить сообщение, если оно еще не отправлено.

        Returns:
            True, если статус изменился.
        """
        if self.status not in (MessageStatus.PENDING, MessageStatus.QUEUED):
            return False
        self.status = MessageStatus.CANCELLED
        self.next_attempt_at = None
        return True


TERMINAL_MESSAGE_STATUSES: frozenset[MessageStatus] = frozenset(
    {MessageStatus.SENT, MessageStatus.FAILED, MessageStatus.CANCELLED}
)


@dataclass(frozen=True, slots=True)
class MessageAttempt:
    """Результат попытки доставки, полученный из очереди.

    Attributes:
        message_id: Сообщение, к которому относится попытка.
        attempt_number: Номер попытки, первая попытка имеет номер 1.
        outcome: Результат попытки.
        occurred_at: Время получения результата.
        provider_message_id: Идентификатор письма провайдера.
        provider_error_code: Код ошибки провайдера.
    """

    message_id: MessageId
    attempt_number: int
    outcome: DeliveryOutcome
    occurred_at: datetime
    provider_message_id: str | None
    provider_error_code: str | None
