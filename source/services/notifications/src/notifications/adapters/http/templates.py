"""Маршруты управления логическими шаблонами."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, status

from notifications.adapters.http.constants import (
    TEMPLATE_PATH,
    TEMPLATE_VERSION_PATH,
    TEMPLATES_PATH,
    TEMPLATES_TAG,
)
from notifications.adapters.http.context import build_request_context
from notifications.adapters.http.schemas import (
    CreateTemplateRequest,
    TemplateListResponse,
    TemplateResponse,
    UpdateTemplateStatusRequest,
    template_page_to_response,
    template_to_response,
)
from notifications.application.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from notifications.application.templates import (
    CreateTemplateCommand,
    TemplateService,
)
from notifications.domain import TemplateKey, TemplateStatus
from notifications.domain.template import MAX_TEMPLATE_KEY_LENGTH, TEMPLATE_KEY_PATTERN

router = APIRouter(tags=[TEMPLATES_TAG])


@router.get(
    TEMPLATES_PATH,
    response_model=TemplateListResponse,
    operation_id="listTemplates",
)
async def list_templates(
    request: Request,
    status_filter: Annotated[
        TemplateStatus | None,
        Query(alias="status", description="Фильтр по статусу версии"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TemplateListResponse:
    """Вернуть страницу версий логических шаблонов."""
    page = await _service(request).list_templates(
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return template_page_to_response(page)


@router.post(
    TEMPLATES_PATH,
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createTemplate",
)
async def create_template(
    request: Request,
    payload: CreateTemplateRequest,
) -> TemplateResponse:
    """Создать версию логического шаблона в статусе draft."""
    template = await _service(request).create_template(
        CreateTemplateCommand(
            key=payload.key,
            version=payload.version,
            description=payload.description,
            required_variables=tuple(payload.required_variables),
        ),
        build_request_context(),
    )
    return template_to_response(template)


@router.get(
    TEMPLATE_PATH,
    response_model=TemplateResponse,
    operation_id="getTemplate",
)
async def get_template(
    request: Request,
    template_key: Annotated[
        str,
        Path(
            min_length=1,
            max_length=MAX_TEMPLATE_KEY_LENGTH,
            pattern=TEMPLATE_KEY_PATTERN,
        ),
    ],
    version: Annotated[int | None, Query(ge=1)] = None,
) -> TemplateResponse:
    """Вернуть версию шаблона или последнюю активную."""
    template = await _service(request).get_template(TemplateKey(template_key), version)
    return template_to_response(template)


@router.patch(
    TEMPLATE_VERSION_PATH,
    response_model=TemplateResponse,
    operation_id="updateTemplateStatus",
)
async def update_template_status(
    request: Request,
    template_key: Annotated[
        str,
        Path(
            min_length=1,
            max_length=MAX_TEMPLATE_KEY_LENGTH,
            pattern=TEMPLATE_KEY_PATTERN,
        ),
    ],
    version: Annotated[int, Path(ge=1)],
    payload: UpdateTemplateStatusRequest,
) -> TemplateResponse:
    """Изменить статус версии шаблона."""
    template = await _service(request).update_status(
        TemplateKey(template_key),
        version,
        payload.status,
        build_request_context(),
    )
    return template_to_response(template)


def _service(request: Request) -> TemplateService:
    """Вернуть сервис шаблонов из состояния приложения."""
    service: TemplateService = request.app.state.template_service
    return service
