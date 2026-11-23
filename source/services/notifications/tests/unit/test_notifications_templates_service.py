"""Проверка сценариев управления логическими шаблонами."""

from datetime import timedelta
from typing import Any

import pytest

from notifications.application.common import RequestContext
from notifications.application.templates import (
    CreateTemplateCommand,
    TemplateService,
)
from notifications.domain import (
    AuditAction,
    ConflictError,
    InvalidStateError,
    NotFoundError,
    TemplateKey,
    TemplateStatus,
    ValidationError,
)

_CONTEXT = RequestContext(correlation_id="corr-1", trace_id="abc123")


def _command(version: int = 1) -> CreateTemplateCommand:
    """Собрать команду создания шаблона."""
    return CreateTemplateCommand(
        key="payment-reminder",
        version=version,
        description="Напоминание об оплате",
        required_variables=("debtor_name", "amount"),
    )


async def test_create_template_persists_and_writes_audit(
    template_harness: Any,
) -> None:
    """Создание сохраняет шаблон и audit-событие в одной фиксации."""
    service: TemplateService = template_harness.service

    template = await service.create_template(_command(), _CONTEXT)

    assert template.status is TemplateStatus.DRAFT
    assert template.key == TemplateKey("payment-reminder")
    assert template_harness.factory.units[-1].committed is True
    stored = await template_harness.repository.get(template.key, template.version)
    assert stored is not None
    assert stored.description == "Напоминание об оплате"
    assert len(template_harness.audits) == 1
    event = template_harness.audits[0]
    assert event.action is AuditAction.TEMPLATE_CREATED
    assert event.entity_type == "template"
    assert event.entity_id == "payment-reminder:1"
    assert event.details == {"key": "payment-reminder", "version": "1"}
    assert event.correlation_id == "corr-1"
    assert event.trace_id == "abc123"


async def test_create_template_rejects_duplicate_version(
    template_harness: Any,
) -> None:
    """Повторная версия с тем же ключом даёт конфликт."""
    service = template_harness.service
    await service.create_template(_command(), _CONTEXT)
    template_harness.audits.clear()

    with pytest.raises(ConflictError):
        await service.create_template(_command(), _CONTEXT)

    assert template_harness.audits == []


async def test_get_template_returns_requested_version(
    template_harness: Any,
) -> None:
    """Версия возвращается по номеру."""
    service = template_harness.service
    await service.create_template(_command(version=1), _CONTEXT)
    await service.create_template(_command(version=2), _CONTEXT)

    template = await service.get_template(TemplateKey("payment-reminder"), 1)

    assert template.version == 1


async def test_get_template_without_version_returns_latest_active(
    template_harness: Any,
) -> None:
    """Без версии возвращается последняя активная версия."""
    service = template_harness.service
    await service.create_template(_command(version=1), _CONTEXT)
    await service.create_template(_command(version=2), _CONTEXT)
    await service.update_status(
        TemplateKey("payment-reminder"),
        1,
        TemplateStatus.ACTIVE,
        _CONTEXT,
    )

    template = await service.get_template(TemplateKey("payment-reminder"))

    assert template.version == 1
    assert template.status is TemplateStatus.ACTIVE


async def test_get_missing_template_raises_not_found(
    template_harness: Any,
) -> None:
    """Отсутствующий шаблон даёт NotFoundError."""
    with pytest.raises(NotFoundError):
        await template_harness.service.get_template(TemplateKey("missing"))


async def test_activation_archives_previous_active_version(
    template_harness: Any,
) -> None:
    """Активация новой версии переводит старую в архив."""
    service = template_harness.service
    await service.create_template(_command(version=1), _CONTEXT)
    await service.create_template(_command(version=2), _CONTEXT)
    await service.update_status(
        TemplateKey("payment-reminder"),
        1,
        TemplateStatus.ACTIVE,
        _CONTEXT,
    )
    template_harness.audits.clear()

    activated = await service.update_status(
        TemplateKey("payment-reminder"),
        2,
        TemplateStatus.ACTIVE,
        _CONTEXT,
    )

    assert activated.status is TemplateStatus.ACTIVE
    previous = await template_harness.repository.get(TemplateKey("payment-reminder"), 1)
    assert previous is not None
    assert previous.status is TemplateStatus.ARCHIVED
    assert len(template_harness.audits) == 1
    event = template_harness.audits[0]
    assert event.action is AuditAction.TEMPLATE_STATUS_CHANGED
    assert event.details == {
        "key": "payment-reminder",
        "version": "2",
        "from_status": "draft",
        "to_status": "active",
    }


async def test_update_status_rejects_forbidden_transition(
    template_harness: Any,
) -> None:
    """Запрещённый переход даёт InvalidStateError и не пишет аудит."""
    service = template_harness.service
    await service.create_template(_command(), _CONTEXT)
    await service.update_status(
        TemplateKey("payment-reminder"),
        1,
        TemplateStatus.ACTIVE,
        _CONTEXT,
    )
    template_harness.audits.clear()

    with pytest.raises(InvalidStateError):
        await service.update_status(
            TemplateKey("payment-reminder"),
            1,
            TemplateStatus.DRAFT,
            _CONTEXT,
        )

    assert template_harness.audits == []


async def test_update_status_to_same_value_is_idempotent(
    template_harness: Any,
) -> None:
    """Повтор статуса не пишет audit-событие."""
    service = template_harness.service
    await service.create_template(_command(), _CONTEXT)
    template_harness.audits.clear()

    template = await service.update_status(
        TemplateKey("payment-reminder"),
        1,
        TemplateStatus.DRAFT,
        _CONTEXT,
    )

    assert template.status is TemplateStatus.DRAFT
    assert template_harness.audits == []


async def test_update_missing_template_raises_not_found(
    template_harness: Any,
) -> None:
    """Изменение отсутствующей версии даёт NotFoundError."""
    with pytest.raises(NotFoundError):
        await template_harness.service.update_status(
            TemplateKey("missing"),
            1,
            TemplateStatus.ACTIVE,
            _CONTEXT,
        )


async def test_list_templates_filters_and_counts(
    template_harness: Any,
) -> None:
    """Список возвращает страницу и общее число с учётом фильтра."""
    service = template_harness.service
    await service.create_template(_command(version=1), _CONTEXT)
    await service.create_template(_command(version=2), _CONTEXT)
    await service.update_status(
        TemplateKey("payment-reminder"),
        1,
        TemplateStatus.ACTIVE,
        _CONTEXT,
    )

    page = await service.list_templates(status=TemplateStatus.DRAFT, limit=10, offset=0)
    everything = await service.list_templates(status=None, limit=10, offset=0)

    assert page.total == 1
    assert [template.version for template in page.items] == [2]
    assert everything.total == 2
    assert [template.version for template in everything.items] == [2, 1]


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (201, 0), (10, -1)])
async def test_list_templates_validates_page(
    template_harness: Any,
    limit: int,
    offset: int,
) -> None:
    """Недопустимая страница даёт ValidationError."""
    with pytest.raises(ValidationError):
        await template_harness.service.list_templates(
            status=None,
            limit=limit,
            offset=offset,
        )


async def test_updated_at_uses_clock(template_harness: Any) -> None:
    """Время изменения берётся из часов сервиса."""
    service = template_harness.service
    await service.create_template(_command(), _CONTEXT)
    later = template_harness.clock.now() + timedelta(minutes=5)
    template_harness.clock.set(later)

    template = await service.update_status(
        TemplateKey("payment-reminder"),
        1,
        TemplateStatus.ACTIVE,
        _CONTEXT,
    )

    assert template.updated_at == later
