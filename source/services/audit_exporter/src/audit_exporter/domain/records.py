"""Записи журнала аудита и фильтры чтения."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from audit_exporter.domain.audit import AuditEvent
from audit_exporter.domain.enums import AuditAction
from audit_exporter.domain.ids import CampaignId, Channel

DEFAULT_PAGE_SIZE: Final = 100
MAX_PAGE_SIZE: Final = 1000


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """Запись append-only журнала.

    Attributes:
        sequence: Порядковый номер записи, назначает хранилище.
        event: Исходное событие без изменений.
        ingested_at: Время записи в журнал.
    """

    sequence: int
    event: AuditEvent
    ingested_at: datetime


@dataclass(frozen=True, slots=True)
class AuditFilter:
    """Фильтры и параметры страницы журнала.

    Attributes:
        campaign_id: Фильтр по кампании.
        channel: Фильтр по каналу.
        action: Фильтр по действию.
        occurred_from: Нижняя граница occurred_at, включительно.
        occurred_to: Верхняя граница occurred_at, не включительно.
        cursor: Курсор следующей страницы.
        limit: Размер страницы.
    """

    campaign_id: CampaignId | None = None
    channel: Channel | None = None
    action: AuditAction | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    cursor: str | None = None
    limit: int = DEFAULT_PAGE_SIZE


@dataclass(frozen=True, slots=True)
class AuditPage:
    """Страница журнала аудита.

    Attributes:
        items: Записи текущей страницы.
        next_cursor: Курсор следующей страницы или None.
    """

    items: tuple[AuditRecord, ...]
    next_cursor: str | None
