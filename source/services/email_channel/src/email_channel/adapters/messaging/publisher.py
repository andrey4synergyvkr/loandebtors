"""Публикация сообщений в RabbitMQ."""

from collections.abc import Mapping

from aio_pika import DeliveryMode, Message

from email_channel.adapters.messaging.connection import RabbitMQConnection
from email_channel.adapters.messaging.constants import CONTENT_TYPE_JSON
from email_channel.adapters.messaging.serialization import encode_payload


class RabbitMQPublisher:
    """Публикатор с publisher confirms и обязательной маршрутизацией."""

    def __init__(self, connection: RabbitMQConnection) -> None:
        """Сохранить управляемое подключение."""
        self._connection = connection

    async def ensure_ready(self) -> None:
        """Убедиться, что соединение и топология готовы."""
        await self._connection.start()

    async def publish(
        self,
        exchange: str,
        routing_key: str,
        payload: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> None:
        """Опубликовать сообщение и дождаться подтверждения брокера."""
        channel = await self._connection.channel()
        target = await channel.get_exchange(exchange, ensure=False)
        message = Message(
            body=encode_payload(payload),
            content_type=CONTENT_TYPE_JSON,
            delivery_mode=DeliveryMode.PERSISTENT,
            headers=dict(headers),
        )
        await target.publish(message, routing_key=routing_key, mandatory=True)

    async def publish_raw(
        self,
        exchange: str,
        routing_key: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> None:
        """Опубликовать исходное тело сообщения и дождаться подтверждения."""
        channel = await self._connection.channel()
        target = await channel.get_exchange(exchange, ensure=False)
        message = Message(
            body=body,
            content_type=CONTENT_TYPE_JSON,
            delivery_mode=DeliveryMode.PERSISTENT,
            headers=dict(headers),
        )
        await target.publish(message, routing_key=routing_key, mandatory=True)
