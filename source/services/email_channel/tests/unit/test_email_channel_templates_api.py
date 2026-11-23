"""Проверка API email-шаблонов."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from email_channel.adapters.http.constants import TEMPLATE_VERSION_PATH, TEMPLATES_PATH
from email_channel.adapters.http.problems import (
    NOT_FOUND_TYPE,
    PROBLEM_MEDIA_TYPE,
    VALIDATION_TYPE,
)
from email_channel.application.config import RequestContext
from email_channel.application.templates import TemplatePage, UpsertEmailTemplateCommand
from email_channel.config import Settings
from email_channel.domain import EmailTemplate, NotFoundError, TemplateKey
from email_channel.main import create_app

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
_KEY = "payment-reminder"


class FakeTemplateService:
    """Сервис шаблонов с заданным ответом."""

    def __init__(self, template: EmailTemplate | None = None) -> None:
        """Сохранить шаблон."""
        self.template = template
        self.command: UpsertEmailTemplateCommand | None = None
        self.context: RequestContext | None = None

    async def list_templates(
        self,
        key: TemplateKey | None,
        locale: str | None,
        limit: int,
        offset: int,
    ) -> TemplatePage:
        """Вернуть страницу с одним шаблоном."""
        items = (self.template,) if self.template is not None else ()
        return TemplatePage(items=items, total=len(items), limit=limit, offset=offset)

    async def get_template(
        self,
        key: TemplateKey,
        version: int,
        locale: str | None = None,
    ) -> EmailTemplate:
        """Вернуть шаблон или ошибку."""
        if self.template is None:
            raise NotFoundError("Шаблон не найден")
        return self.template

    async def upsert_template(
        self,
        command: UpsertEmailTemplateCommand,
        context: RequestContext,
    ) -> EmailTemplate:
        """Запомнить команду и вернуть шаблон."""
        self.command = command
        self.context = context
        if self.template is None:
            raise NotFoundError("Шаблон не найден")
        return self.template


def _template() -> EmailTemplate:
    return EmailTemplate(
        key=TemplateKey(_KEY),
        version=1,
        locale="ru-RU",
        subject_template="Тема",
        html_template="<p>Текст</p>",
        plain_text_template="Текст",
        required_variables=("name",),
        updated_at=_NOW,
    )


def _payload() -> dict[str, object]:
    return {
        "locale": "ru-RU",
        "subject_template": "Тема",
        "html_template": "<p>Текст</p>",
        "plain_text_template": "Текст",
        "required_variables": ["name"],
    }


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Создать тестовый клиент с пустым сервисом шаблонов."""
    app = create_app(
        Settings(
            service_name="email_channel",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    app.state.email_template_service = FakeTemplateService(None)
    with TestClient(app) as test_client:
        yield test_client


def test_list_templates_returns_page(client: TestClient) -> None:
    """Список шаблонов отдаётся в формате контракта."""
    client.app.state.email_template_service = FakeTemplateService(_template())  # type: ignore[attr-defined]

    response = client.get(TEMPLATES_PATH, params={"limit": 10, "offset": 0})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["limit"] == 10
    assert payload["items"][0]["key"] == _KEY


def test_get_template_returns_not_found_problem(client: TestClient) -> None:
    """Отсутствующий шаблон даёт 404 Problem."""
    response = client.get(TEMPLATE_VERSION_PATH.format(template_key=_KEY, version=1))

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.json()["type"] == NOT_FOUND_TYPE


def test_upsert_template_returns_template(client: TestClient) -> None:
    """PUT передаёт команду и возвращает шаблон."""
    service = FakeTemplateService(_template())
    client.app.state.email_template_service = service  # type: ignore[attr-defined]

    response = client.put(
        TEMPLATE_VERSION_PATH.format(template_key=_KEY, version=1),
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.json()["key"] == _KEY
    assert service.command is not None
    assert service.command.locale == "ru-RU"
    assert service.command.required_variables == ("name",)
    assert service.context is not None


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (TEMPLATE_VERSION_PATH.format(template_key="Bad Key", version=1), _payload()),
        (TEMPLATE_VERSION_PATH.format(template_key=_KEY, version=0), _payload()),
        (
            TEMPLATE_VERSION_PATH.format(template_key=_KEY, version=1),
            {**_payload(), "locale": "ru_RU"},
        ),
        (
            TEMPLATE_VERSION_PATH.format(template_key=_KEY, version=1),
            {**_payload(), "required_variables": ["name", "name"]},
        ),
        (
            TEMPLATE_VERSION_PATH.format(template_key=_KEY, version=1),
            {**_payload(), "unknown": "value"},
        ),
    ],
)
def test_upsert_template_returns_validation_problem(
    client: TestClient,
    path: str,
    payload: dict[str, object],
) -> None:
    """Невалидный запрос даёт 422 Problem."""
    response = client.put(path, json=payload)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.json()["type"] == VALIDATION_TYPE
