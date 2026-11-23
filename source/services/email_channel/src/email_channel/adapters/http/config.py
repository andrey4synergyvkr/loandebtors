"""Маршруты настройки SMTP-адаптера."""

from fastapi import APIRouter, Request

from email_channel.adapters.http.constants import (
    CHANNEL_TAG,
    CONFIG_PATH,
    CONFIG_VALIDATE_PATH,
)
from email_channel.adapters.http.context import build_request_context
from email_channel.adapters.http.problems import PROBLEM_MEDIA_TYPE, Problem
from email_channel.adapters.http.schemas import (
    SmtpConfigRequest,
    SmtpConfigResponse,
    ValidationResultResponse,
    config_to_response,
    validation_to_response,
)
from email_channel.application.config import (
    ChannelConfigService,
    UpdateChannelConfigCommand,
)

router = APIRouter(tags=[CHANNEL_TAG])


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
    CONFIG_PATH,
    response_model=SmtpConfigResponse,
    operation_id="getChannelConfig",
    responses={404: _problem_response("Настройки не заданы")},
)
async def get_channel_config(request: Request) -> SmtpConfigResponse:
    """Вернуть настройки SMTP-адаптера."""
    config = await _service(request).get_config()
    return config_to_response(config)


@router.put(
    CONFIG_PATH,
    response_model=SmtpConfigResponse,
    operation_id="updateChannelConfig",
    responses={422: _problem_response("Ошибка валидации запроса")},
)
async def update_channel_config(
    request: Request,
    payload: SmtpConfigRequest,
) -> SmtpConfigResponse:
    """Сохранить настройки и записать channel.config.updated."""
    config = await _service(request).update_config(
        _command_from_payload(payload),
        build_request_context(),
    )
    return config_to_response(config)


@router.post(
    CONFIG_VALIDATE_PATH,
    response_model=ValidationResultResponse,
    operation_id="validateChannelConfig",
    responses={422: _problem_response("Ошибка валидации запроса")},
)
async def validate_channel_config(
    request: Request,
    payload: SmtpConfigRequest,
) -> ValidationResultResponse:
    """Проверить настройки и доступность SMTP без сохранения."""
    result = await _service(request).validate_config(_command_from_payload(payload))
    return validation_to_response(result)


def _command_from_payload(payload: SmtpConfigRequest) -> UpdateChannelConfigCommand:
    """Собрать команду из тела запроса."""
    return UpdateChannelConfigCommand(
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password_ref=payload.password_ref,
        from_address=payload.from_address,
        from_name=payload.from_name,
        use_starttls=payload.use_starttls,
        timeout_seconds=payload.timeout_seconds,
        rate_limit_per_second=payload.rate_limit_per_second,
        enabled=payload.enabled,
    )


def _service(request: Request) -> ChannelConfigService:
    """Вернуть сервис настроек из состояния приложения."""
    service: ChannelConfigService = request.app.state.channel_config_service
    return service
