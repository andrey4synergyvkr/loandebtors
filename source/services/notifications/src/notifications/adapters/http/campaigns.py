"""Маршруты управления кампаниями."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from notifications.adapters.http.constants import (
    CAMPAIGN_CANCEL_PATH,
    CAMPAIGN_PATH,
    CAMPAIGN_SCHEDULE_PATH,
    CAMPAIGN_START_PATH,
    CAMPAIGNS_PATH,
    CAMPAIGNS_TAG,
)
from notifications.adapters.http.context import build_request_context
from notifications.adapters.http.schemas import (
    CampaignListResponse,
    CampaignResponse,
    CreateCampaignRequest,
    ScheduleCampaignRequest,
    UpdateCampaignRequest,
    campaign_page_to_response,
    campaign_to_response,
    schedule_from_schema,
    selection_from_schema,
)
from notifications.application.campaigns import (
    CampaignService,
    CreateCampaignCommand,
    UpdateCampaignCommand,
)
from notifications.application.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from notifications.domain import CampaignId, CampaignStatus, Channel, TemplateKey

router = APIRouter(tags=[CAMPAIGNS_TAG])


@router.get(
    CAMPAIGNS_PATH,
    response_model=CampaignListResponse,
    operation_id="listCampaigns",
)
async def list_campaigns(
    request: Request,
    status_filter: Annotated[
        CampaignStatus | None,
        Query(alias="status", description="Фильтр по статусу кампании"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CampaignListResponse:
    """Вернуть страницу кампаний."""
    page = await _service(request).list_campaigns(
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return campaign_page_to_response(page)


@router.post(
    CAMPAIGNS_PATH,
    response_model=CampaignResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCampaign",
)
async def create_campaign(
    request: Request,
    payload: CreateCampaignRequest,
) -> CampaignResponse:
    """Создать кампанию в статусе draft."""
    campaign = await _service(request).create_campaign(
        CreateCampaignCommand(
            name=payload.name,
            channel=Channel(payload.channel),
            template_key=TemplateKey(payload.template_key),
            template_version=payload.template_version,
            selection=selection_from_schema(payload.selection),
        ),
        build_request_context(),
    )
    return campaign_to_response(campaign)


@router.get(
    CAMPAIGN_PATH,
    response_model=CampaignResponse,
    operation_id="getCampaign",
)
async def get_campaign(request: Request, campaign_id: UUID) -> CampaignResponse:
    """Вернуть кампанию по идентификатору."""
    campaign = await _service(request).get_campaign(CampaignId(campaign_id))
    return campaign_to_response(campaign)


@router.patch(
    CAMPAIGN_PATH,
    response_model=CampaignResponse,
    operation_id="updateCampaign",
)
async def update_campaign(
    request: Request,
    campaign_id: UUID,
    payload: UpdateCampaignRequest,
) -> CampaignResponse:
    """Изменить кампанию в статусе draft."""
    campaign = await _service(request).update_campaign(
        CampaignId(campaign_id),
        UpdateCampaignCommand(
            name=payload.name,
            template_key=(TemplateKey(payload.template_key) if payload.template_key is not None else None),
            template_version=payload.template_version,
            selection=(selection_from_schema(payload.selection) if payload.selection is not None else None),
        ),
        build_request_context(),
    )
    return campaign_to_response(campaign)


@router.post(
    CAMPAIGN_SCHEDULE_PATH,
    response_model=CampaignResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="scheduleCampaign",
)
async def schedule_campaign(
    request: Request,
    campaign_id: UUID,
    payload: ScheduleCampaignRequest,
) -> CampaignResponse:
    """Поставить draft-кампанию в расписание."""
    campaign = await _service(request).schedule_campaign(
        CampaignId(campaign_id),
        schedule_from_schema(payload.schedule),
        build_request_context(),
    )
    return campaign_to_response(campaign)


@router.post(
    CAMPAIGN_CANCEL_PATH,
    response_model=CampaignResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="cancelCampaign",
)
async def cancel_campaign(request: Request, campaign_id: UUID) -> CampaignResponse:
    """Отменить запланированную кампанию."""
    campaign = await _service(request).cancel_campaign(
        CampaignId(campaign_id),
        build_request_context(),
    )
    return campaign_to_response(campaign)


@router.post(
    CAMPAIGN_START_PATH,
    response_model=CampaignResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="startCampaign",
)
async def start_campaign(request: Request, campaign_id: UUID) -> CampaignResponse:
    """Запустить кампанию немедленно."""
    campaign = await _service(request).start_campaign(
        CampaignId(campaign_id),
        build_request_context(),
    )
    return campaign_to_response(campaign)


def _service(request: Request) -> CampaignService:
    """Вернуть сервис кампаний из состояния приложения."""
    service: CampaignService = request.app.state.campaign_service
    return service
