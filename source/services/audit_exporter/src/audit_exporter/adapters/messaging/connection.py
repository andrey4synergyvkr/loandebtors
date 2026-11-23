"""Управление подключением к RabbitMQ."""

import asyncio
from contextlib import suppress

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractConnection

from audit_exporter.adapters.messaging.topology import declare_topology
from audit_exporter.config import Settings


class RabbitMQConnection:
    """Robust-подключение и канал RabbitMQ с объявленной топологией."""

    def __init__(self, settings: Settings) -> None:
        """Сохранить настройки подключения."""
        self._settings = settings
        self._lock = asyncio.Lock()
        self._connection: AbstractConnection | None = None
        self._channel: AbstractChannel | None = None

    async def start(self) -> None:
        """Установить соединение и объявить топологию, если его еще нет."""
        async with self._lock:
            if (
                self._connection is not None
                and not self._connection.is_closed
                and self._channel is not None
                and not self._channel.is_closed
            ):
                return
            await self._close_unlocked()
            connection = await aio_pika.connect_robust(
                self._settings.rabbitmq_url,
                timeout=self._settings.rabbitmq_connection_timeout,
            )
            try:
                channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
                await channel.set_qos(prefetch_count=self._settings.rabbitmq_prefetch_count)
                await declare_topology(
                    channel,
                    retry_ttl_milliseconds=int(self._settings.rabbitmq_retry_ttl_seconds * 1000),
                )
            except Exception:
                with suppress(Exception):
                    await connection.close()
                raise
            self._connection = connection
            self._channel = channel

    async def channel(self) -> AbstractChannel:
        """Вернуть открытый канал, при необходимости подключившись заново."""
        await self.start()
        if self._channel is None:
            raise ConnectionError("Канал RabbitMQ не создан")
        return self._channel

    async def check(self) -> None:
        """Проверить, что соединение установлено и готово к работе."""
        if self._connection is None or self._connection.is_closed:
            raise ConnectionError("Соединение с RabbitMQ не установлено")
        await self._connection.ready()

    async def close(self) -> None:
        """Закрыть канал и соединение."""
        async with self._lock:
            await self._close_unlocked()

    async def _close_unlocked(self) -> None:
        """Закрыть ресурсы без захвата блокировки."""
        channel, self._channel = self._channel, None
        connection, self._connection = self._connection, None
        if channel is not None and not channel.is_closed:
            with suppress(Exception):
                await channel.close()
        if connection is not None and not connection.is_closed:
            with suppress(Exception):
                await connection.close()
