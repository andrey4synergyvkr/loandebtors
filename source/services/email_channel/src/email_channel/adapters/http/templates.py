"""Маршруты email-шаблонов."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request

from email_channel.adapters.http.constants import (
    TEMPLATE_VERSION_PATH,
    TEMPLATES_PATH,
    TEMPLATES_TAG,
)
from email_channel.adapters.http.context import build_request_context
from email_channel.adapters.http.problems import PROBLEM_MEDIA_TYPE, Problem
from email_channel.adapters.http.schemas import (
    EmailTemplateListResponse,
    EmailTemplateRequest,
    EmailTemplateResponse,
    template_page_to_response,
    template_to_response,
)
from email_channel.application.templates import (
    LOCALE_PATTERN,
    TEMPLATE_KEY_PATTERN,
    EmailTemplateService,
    UpsertEmailTemplateCommand,
)
from email_channel.domain import TemplateKey

router = APIRouter(tags=[TEMPLATES_TAG])


def _problem_response(description: str) -> dict[str, object]:
    """Описать ответ Problem с media type application/problem+json."""
    return {
        "description": description,
        "content": {
            PROBLEM_MEDIA_TYPE: {
                "schema": Problem.model_json_schema(),
            }
        },
    }


@router.get(
    TEMPLATES_PATH,
    response_model=EmailTemplateListResponse,
    operation_id="listEmailTemplates",
    responses={422: _problem_response("Ошибка валидации запроса")},
)
async def list_email_templates(
    request: Request,
    template_key: Annotated[
        str | None,
        Query(pattern=TEMPLATE_KEY_PATTERN, max_length=100),
    ] = None,
    locale: Annotated[str | None, Query(pattern=LOCALE_PATTERN, max_length=10)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EmailTemplateListResponse:
    """Вернуть страницу email-шаблонов."""
    page = await _service(request).list_templates(
        key=TemplateKey(template_key) if template_key is not None else None,
        locale=locale,
        limit=limit,
        offset=offset,
    )
    return template_page_to_response(page)


@router.get(
    TEMPLATE_VERSION_PATH,
    response_model=EmailTemplateResponse,
    operation_id="getEmailTemplate",
    responses={
        404: _problem_response("Шаблон не найден"),
        422: _problem_response("Ошибка валидации запроса"),
    },
)
async def get_email_template(
    request: Request,
    template_key: Annotated[
        str,
        Path(pattern=TEMPLATE_KEY_PATTERN, max_length=100),
    ],
    version: Annotated[int, Path(ge=1)],
    locale: Annotated[str | None, Query(pattern=LOCALE_PATTERN, max_length=10)] = None,
) -> EmailTemplateResponse:
    """Вернуть email-шаблон по ключу и версии."""
    template = await _service(request).get_template(
        TemplateKey(template_key),
        version,
        locale,
    )
    return template_to_response(template)


@router.put(
    TEMPLATE_VERSION_PATH,
    response_model=EmailTemplateResponse,
    operation_id="upsertEmailTemplate",
    responses={422: _problem_response("Ошибка валидации запроса")},
)
async def upsert_email_template(
    request: Request,
    template_key: Annotated[
        str,
        Path(pattern=TEMPLATE_KEY_PATTERN, max_length=100),
    ],
    version: Annotated[int, Path(ge=1)],
    payload: EmailTemplateRequest,
) -> EmailTemplateResponse:
    """Создать или обновить email-шаблон."""
    template = await _service(request).upsert_template(
        UpsertEmailTemplateCommand(
            key=template_key,
            version=version,
            locale=payload.locale,
            subject_template=payload.subject_template,
            html_template=payload.html_template,
            plain_text_template=payload.plain_text_template,
            required_variables=tuple(payload.required_variables),
        ),
        build_request_context(),
    )
    return template_to_response(template)


def _service(request: Request) -> EmailTemplateService:
    """Вернуть сервис шаблонов из состояния приложения."""
    service: EmailTemplateService = request.app.state.email_template_service
    return service
