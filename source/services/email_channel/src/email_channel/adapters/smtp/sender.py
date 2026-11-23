"""Отправка писем через aiosmtplib."""

from contextlib import suppress
from datetime import UTC, datetime
from email.message import EmailMessage

import aiosmtplib

from email_channel.domain import (
    DeliveryOutcome,
    RenderedEmail,
    SendFailure,
    SendReceipt,
    SendResult,
    SmtpConfig,
)

ERROR_MESSAGE_LIMIT: int = 500


class AiosmtplibEmailSender:
    """Отправляет MIME-письма через SMTP-провайдера."""

    async def send(
        self,
        config: SmtpConfig,
        email: RenderedEmail,
        password: str,
    ) -> SendResult:
        """Отправить письмо и классифицировать ошибку."""
        try:
            message = EmailMessage()
            message["From"] = f"{config.from_name} <{config.from_address}>"
            message["To"] = email.recipient
            message["Subject"] = email.subject
            message.set_content(email.plain_text_body)
            message.add_alternative(email.html_body, subtype="html")
        except (ValueError, TypeError) as exc:
            return SendFailure(
                outcome=DeliveryOutcome.PERMANENT_FAILURE,
                provider_error_code="invalid_message",
                provider_error_message=str(exc)[:ERROR_MESSAGE_LIMIT],
            )

        client = aiosmtplib.SMTP(
            hostname=config.host,
            port=config.port,
            timeout=config.timeout_seconds,
            start_tls=config.use_starttls,
        )
        try:
            await client.connect()
            if config.username and password:
                await client.login(config.username, password)
            await client.send_message(message)
        except aiosmtplib.SMTPRecipientsRefused:
            return SendFailure(
                outcome=DeliveryOutcome.PERMANENT_FAILURE,
                provider_error_code="recipients_refused",
                provider_error_message="Провайдер отклонил получателя",
            )
        except aiosmtplib.SMTPResponseException as exc:
            outcome = (
                DeliveryOutcome.PERMANENT_FAILURE if exc.code >= 500 else DeliveryOutcome.TRANSIENT_FAILURE
            )
            return SendFailure(
                outcome=outcome,
                provider_error_code=str(exc.code),
                provider_error_message=str(exc.message)[:ERROR_MESSAGE_LIMIT],
            )
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
            return SendFailure(
                outcome=DeliveryOutcome.TRANSIENT_FAILURE,
                provider_error_code=type(exc).__name__,
                provider_error_message=str(exc)[:ERROR_MESSAGE_LIMIT],
            )
        finally:
            with suppress(Exception):
                await client.quit()
        return SendReceipt(
            provider_message_id=None,
            accepted_at=datetime.now(UTC),
        )
