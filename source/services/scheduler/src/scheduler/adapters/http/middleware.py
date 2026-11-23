"""HTTP-middleware корреляции запросов, метрик и access-логов."""

import logging
import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from scheduler.adapters.http.constants import HEALTH_PATH, REQUEST_ID_HEADER
from scheduler.infrastructure.correlation import (
    bind_correlation_id,
    new_correlation_id,
    reset_correlation_id,
)
from scheduler.infrastructure.metrics import (
    HTTP_METHOD_ATTRIBUTE,
    HTTP_ROUTE_ATTRIBUTE,
    HTTP_STATUS_ATTRIBUTE,
    Metrics,
)

access_logger = logging.getLogger("scheduler.access")


class CorrelationIdMiddleware:
    """Добавляет идентификатор корреляции в контекст и ответ."""

    def __init__(self, app: ASGIApp) -> None:
        """Сохранить вложенное ASGI-приложение."""
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Обработать запрос с идентификатором корреляции."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        correlation_id = headers.get(REQUEST_ID_HEADER) or new_correlation_id()
        token = bind_correlation_id(correlation_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers.append(REQUEST_ID_HEADER, correlation_id)
            await send(message)

        try:
            await self._app(scope, receive, send_with_header)
        finally:
            reset_correlation_id(token)


class HttpMetricsMiddleware:
    """Считает метрики HTTP и пишет структурированный access-лог."""

    def __init__(
        self,
        app: ASGIApp,
        metrics: Metrics,
        access_log_health_enabled: bool = False,
    ) -> None:
        """Сохранить вложенное приложение, метрики и настройку логов health."""
        self._app = app
        self._metrics = metrics
        self._access_log_health_enabled = access_log_health_enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Записать метрики и access-лог после завершения запроса."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        started_at = time.monotonic()
        status_code: int | None = None

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, send_with_status)
        finally:
            route = scope.get("route")
            route_path = getattr(route, "path", None)
            path_value = route_path if isinstance(route_path, str) else "unmatched"
            method = str(scope.get("method", ""))
            status = status_code or 0
            duration_ms = round((time.monotonic() - started_at) * 1000, 3)
            attributes: dict[str, str | int] = {
                HTTP_METHOD_ATTRIBUTE: method,
                HTTP_ROUTE_ATTRIBUTE: path_value,
                HTTP_STATUS_ATTRIBUTE: status,
            }
            self._metrics.http_requests.add(1, attributes)
            self._metrics.http_duration.record(time.monotonic() - started_at, attributes)

            if path_value != HEALTH_PATH or self._access_log_health_enabled:
                log_attributes: dict[str, str | int | float] = {
                    "event": "http_request",
                    "http_method": method,
                    "http_route": path_value,
                    "http_status_code": status,
                    "duration_ms": duration_ms,
                }
                message = "HTTP %s %s %s"
                if status >= 500 or status == 0:
                    access_logger.error(message, method, path_value, status, extra=log_attributes)
                elif status >= 400:
                    access_logger.warning(message, method, path_value, status, extra=log_attributes)
                else:
                    access_logger.info(message, method, path_value, status, extra=log_attributes)
