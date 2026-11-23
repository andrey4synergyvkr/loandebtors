"""Проверка HTTP-адаптера АБС на контракте заглушки."""

from collections.abc import AsyncIterator

import httpx
import pytest

from abs.config import Settings as AbsSettings
from abs.main import create_app as create_abs_app
from notifications.adapters.abs.source import HttpAbsDebtorSource
from notifications.config import Settings
from notifications.domain import DebtorFilter
from notifications.ports import AbsPermanentError, AbsTransientError


def _settings(**overrides: object) -> Settings:
    """Собрать настройки адаптера для тестов."""
    values: dict[str, object] = {
        "abs_base_url": "http://abs",
        "abs_timeout_seconds": 5.0,
        "abs_max_attempts": 2,
        "abs_retry_base_seconds": 0.01,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
async def abs_client() -> AsyncIterator[httpx.AsyncClient]:
    """Создать клиент к настоящему приложению заглушки через ASGI."""
    app = create_abs_app(AbsSettings(otel_enabled=False, otel_logs_enabled=False))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://abs") as client:
        yield client


async def test_fetch_page_uses_abs_contract(abs_client: httpx.AsyncClient) -> None:
    """Адаптер читает страницу из заглушки по контракту."""
    source = HttpAbsDebtorSource(_settings(), client=abs_client)

    page = await source.fetch_page(1, 10, DebtorFilter(min_days_overdue=30))

    assert page.page == 1
    assert page.total >= len(page.items)
    assert all(debtor.debts for debtor in page.items)
    assert all(any(debt.days_overdue >= 30 for debt in debtor.debts) for debtor in page.items)


async def test_fetch_page_paginates(abs_client: httpx.AsyncClient) -> None:
    """Вторая страница запрашивается с тем же фильтром."""
    source = HttpAbsDebtorSource(_settings(), client=abs_client)

    first = await source.fetch_page(1, 5, DebtorFilter())
    second = await source.fetch_page(2, 5, DebtorFilter())

    assert first.page == 1
    assert second.page == 2
    assert first.total == second.total
    assert first.has_next is True


async def test_fetch_page_maps_4xx_to_permanent_error(
    abs_client: httpx.AsyncClient,
) -> None:
    """Ошибка параметров АБС не повторяется."""
    source = HttpAbsDebtorSource(_settings(), client=abs_client)

    with pytest.raises(AbsPermanentError):
        await source.fetch_page(1, 0, DebtorFilter())


async def test_fetch_page_retries_5xx() -> None:
    """Две ошибки 5xx и успех завершаются страницей."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(500, json={"error": "server"})
        return httpx.Response(
            200,
            json={
                "items": [],
                "page": 1,
                "total": 0,
                "has_next": False,
            },
        )

    source = HttpAbsDebtorSource(
        _settings(abs_max_attempts=3),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://abs"),
    )

    page = await source.fetch_page(1, 10, DebtorFilter())

    assert page.total == 0
    assert attempts == 3


async def test_fetch_page_exhausts_retries() -> None:
    """После исчерпания попыток возвращается временная ошибка."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    source = HttpAbsDebtorSource(
        _settings(abs_max_attempts=2),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://abs"),
    )

    with pytest.raises(AbsTransientError):
        await source.fetch_page(1, 10, DebtorFilter())


async def test_fetch_page_maps_transport_error() -> None:
    """Сетевая ошибка считается временной."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network", request=request)

    source = HttpAbsDebtorSource(
        _settings(abs_max_attempts=1),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://abs"),
    )

    with pytest.raises(AbsTransientError):
        await source.fetch_page(1, 10, DebtorFilter())


async def test_fetch_page_rejects_invalid_response() -> None:
    """Ответ не по контракту считается постоянной ошибкой."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": "bad", "page": 1})

    source = HttpAbsDebtorSource(
        _settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://abs"),
    )

    with pytest.raises(AbsPermanentError):
        await source.fetch_page(1, 10, DebtorFilter())
