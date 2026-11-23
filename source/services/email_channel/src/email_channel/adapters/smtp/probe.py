"""Проверка TCP-доступности SMTP через asyncio."""

import asyncio


class AsyncioSmtpProbe:
    """Открывает TCP-соединение с SMTP-хостом и сразу закрывает его."""

    async def check(self, host: str, port: int, timeout_seconds: float) -> str | None:
        """Вернуть None, если соединение установлено, или описание ошибки."""
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout_seconds,
            )
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            return None
        return None
