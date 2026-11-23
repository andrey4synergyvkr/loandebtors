"""Маршруты просмотра сообщений кампании."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from notifications.adapters.http.constants import (
    CAMPAIGN_MESSAGE_PATH,
    CAMPAIGN_MESSAGES_PATH,
    MESSAGES_TAG,
)
from notifications.adapters.http.schemas import (
    MessageListResponse,
    MessageResponse,
    message_page_to_response,
    message_to_response,
)
from notifications.application.campaigns import CampaignService
from notifications.application.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from notifications.domain import CampaignId, MessageId, MessageStatus

router = APIRouter(tags=[MESSAGES_TAG])


@router.get(
    CAMPAIGN_MESSAGES_PATH,
    response_model=MessageListResponse,
    operation_id="listCampaignMessages",
)
async def list_campaign_messages(
    request: Request,
    campaign_id: UUID,
    status_filter: Annotated[
        MessageStatus | None,
        Query(alias="status", description="Фильтр по статусу сообщения"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MessageListResponse:
    """Вернуть страницу сообщений кампании."""
    page = await _service(request).list_messages(
        CampaignId(campaign_id),
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return message_page_to_response(page)


@router.get(
    CAMPAIGN_MESSAGE_PATH,
    response_model=MessageResponse,
    operation_id="getCampaignMessage",
)
async def get_campaign_message(
    request: Request,
    campaign_id: UUID,
    message_id: UUID,
) -> MessageResponse:
    """Вернуть сообщение кампании по идентификатору."""
    message = await _service(request).get_message(
        CampaignId(campaign_id),
        MessageId(message_id),
    )
    return message_to_response(message)


def _service(request: Request) -> CampaignService:
    """Вернуть сервис кампаний из состояния приложения."""
    service: CampaignService = request.app.state.campaign_service
    return service
