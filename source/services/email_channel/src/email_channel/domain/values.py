"""Значения доставки Email Channel."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from email_channel.domain.ids import EmailAddress, MessageId


class DeliveryOutcome(StrEnum):
    """Результат попытки доставки.

    Attributes:
        SENT: Провайдер принял сообщение.
        TRANSIENT_FAILURE: Временная ошибка, попытку можно повторить.
        PERMANENT_FAILURE: Постоянная ошибка, повторы бессмысленны.
        RATE_LIMITED: Провайдер ограничил скорость.
    """

    SENT = "sent"
    TRANSIENT_FAILURE = "transient_failure"
    PERMANENT_FAILURE = "permanent_failure"
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    """Готовое к отправке письмо.

    Attributes:
        recipient: Получатель письма.
        subject: Готовая тема.
        html_body: Готовое HTML-тело.
        plain_text_body: Готовое текстовое тело.
    """

    recipient: EmailAddress
    subject: str
    html_body: str
    plain_text_body: str


@dataclass(frozen=True, slots=True)
class SendReceipt:
    """Успешный ответ провайдера.

    Attributes:
        provider_message_id: Идентификатор письма у провайдера.
        accepted_at: Время приема письма.
    """

    provider_message_id: str | None
    accepted_at: datetime


@dataclass(frozen=True, slots=True)
class SendFailure:
    """Ошибка отправки с классификацией.

    Attributes:
        outcome: Классификация ошибки.
        provider_error_code: Код ошибки провайдера.
        provider_error_message: Описание ошибки без персональных данных.
    """

    outcome: DeliveryOutcome
    provider_error_code: str | None
    provider_error_message: str | None


type SendResult = SendReceipt | SendFailure


@dataclass(frozen=True, slots=True)
class SendAttempt:
    """Попытка отправки письма.

    Attributes:
        message_id: Сообщение, к которому относится попытка.
        attempt_number: Номер попытки, начиная с 1.
        recipient: Фактический получатель.
        started_at: Время начала попытки.
        finished_at: Время завершения попытки.
        outcome: Результат попытки.
        provider_message_id: Идентификатор письма у провайдера.
        provider_error_code: Код ошибки провайдера.
        provider_error_message: Описание ошибки без персональных данных.
    """

    message_id: MessageId
    attempt_number: int
    recipient: EmailAddress
    started_at: datetime
    finished_at: datetime | None
    outcome: DeliveryOutcome | None
    provider_message_id: str | None
    provider_error_code: str | None
    provider_error_message: str | None
