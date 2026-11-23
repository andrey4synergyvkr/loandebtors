"""Повторная публикация сообщений из audit.events.dlq."""

import argparse
import asyncio
import os
from typing import Final, cast

import aio_pika
from aio_pika import DeliveryMode

DEFAULT_RABBITMQ_URL: Final = "amqp://loandebtors:loandebtors@localhost:5672/"
EXCHANGE_NAME: Final = "loan-debtors.events"
DLQ_NAME: Final = "audit.events.dlq"
ROUTING_KEY: Final = "audit.event"
CONTENT_TYPE: Final = "application/json"


async def _redrive(
    rabbitmq_url: str,
    limit: int,
    dry_run: bool,
) -> int:
    """Переопубликовать до limit сообщений из DLQ и вернуть их число."""
    connection = await aio_pika.connect_robust(rabbitmq_url)
    republished = 0
    try:
        channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        exchange = await channel.get_exchange(EXCHANGE_NAME, ensure=True)
        queue = await channel.get_queue(DLQ_NAME)
        for _ in range(limit):
            message = await queue.get(no_ack=False, fail=False)
            if message is None:
                break
            if dry_run:
                print(f"dry-run: {message.body[:200]!r}")
                await message.nack(requeue=True)
                republished += 1
                continue
            try:
                await exchange.publish(
                    aio_pika.Message(
                        body=message.body,
                        content_type=CONTENT_TYPE,
                        delivery_mode=DeliveryMode.PERSISTENT,
                        headers=dict(message.headers or {}),
                    ),
                    routing_key=ROUTING_KEY,
                    mandatory=True,
                )
            except Exception:
                await message.nack(requeue=True)
                raise
            await message.ack()
            republished += 1
    finally:
        await connection.close()
    return republished


def main() -> None:
    """Разобрать аргументы и запустить повторную публикацию."""
    parser = argparse.ArgumentParser(description="Повторная публикация audit.events.dlq")
    parser.add_argument(
        "--rabbitmq-url",
        default=os.environ.get("RABBITMQ_URL", DEFAULT_RABBITMQ_URL),
        help="AMQP DSN RabbitMQ",
    )
    parser.add_argument("--limit", type=int, default=100, help="Максимум сообщений")
    parser.add_argument("--dry-run", action="store_true", help="Показать сообщения без публикации")
    args = parser.parse_args()

    republished = asyncio.run(
        _redrive(
            cast(str, args.rabbitmq_url),
            cast(int, args.limit),
            cast(bool, args.dry_run),
        )
    )
    print(f"Обработано сообщений: {republished}")


if __name__ == "__main__":
    main()
