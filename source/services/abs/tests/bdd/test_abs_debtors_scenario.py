"""BDD-сценарии постраничной выгрузки должников."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pytest_bdd import given, parsers, scenario, then, when

from abs.adapters.http.constants import DEBTORS_PATH
from abs.config import Settings
from abs.main import create_app

pytestmark = pytest.mark.bdd


@scenario("features/debtors.feature", "Первая страница сообщает общее число должников")
def test_first_page() -> None:
    """Сценарий выполняется шагами ниже."""


@scenario("features/debtors.feature", "Последняя страница закрывает выборку")
def test_last_page() -> None:
    """Сценарий выполняется шагами ниже."""


@scenario("features/debtors.feature", "Страница за пределами выборки пуста")
def test_page_beyond_selection() -> None:
    """Сценарий выполняется шагами ниже."""


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Создать тестовый клиент заглушки."""
    app = create_app(Settings(service_name="abs", otel_enabled=False))
    with TestClient(app) as test_client:
        yield test_client


@given("заглушка АБС запущена")
def service_is_running(client: TestClient) -> None:
    """Подготовить запущенный клиент заглушки."""
    assert client is not None


@when(
    parsers.parse("запрашивается страница {page:d} размером {page_size:d}"),
    target_fixture="response",
)
def request_page(client: TestClient, page: int, page_size: int) -> Response:
    """Запросить страницу выгрузки."""
    response: Response = client.get(
        DEBTORS_PATH,
        params={"page": page, "page_size": page_size},
    )
    return response


@then(parsers.parse("ответ содержит {count:d} должников, total {total:d} и признак следующей страницы"))
def check_page_with_next(response: Response, count: int, total: int) -> None:
    """Проверить размер страницы, total и наличие следующей страницы."""
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == count
    assert payload["total"] == total
    assert payload["has_next"] is True


@then(parsers.parse("ответ содержит {count:d} должников и не имеет следующей страницы"))
def check_last_page(response: Response, count: int) -> None:
    """Проверить последнюю страницу выборки."""
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == count
    assert payload["total"] == 24
    assert payload["has_next"] is False


@then("ответ не содержит должников и не имеет следующей страницы")
def check_empty_page(response: Response) -> None:
    """Проверить пустую страницу за пределами выборки."""
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["total"] == 24
    assert payload["has_next"] is False
