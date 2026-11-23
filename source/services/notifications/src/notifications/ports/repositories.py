"""Порты репозиториев Notifications."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from notifications.domain import (
    Campaign,
    CampaignId,
    CampaignStatus,
    DebtorSnapshot,
    MessageAttempt,
    MessageId,
    MessageStatus,
    NotificationMessage,
    NotificationTemplate,
    TemplateKey,
    TemplateStatus,
)


class CampaignRepository(Protocol):
    """Доступ к кампаниям."""

    async def add(self, campaign: Campaign) -> None:
        """Создать новую кампанию."""
        ...

    async def get(self, campaign_id: CampaignId) -> Campaign | None:
        """Вернуть кампанию или None."""
        ...

    async def save(self, campaign: Campaign) -> None:
        """Сохранить изменения существующей кампании."""
        ...

    async def list(
        self,
        status: CampaignStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Campaign]:
        """Вернуть страницу кампаний с фильтром по статусу."""
        ...

    async def count(self, status: CampaignStatus | None = None) -> int:
        """Вернуть число кампаний с фильтром по статусу."""
        ...

    async def try_advisory_lock(self, campaign_id: CampaignId) -> bool:
        """Попробовать взять транзакционную блокировку обработки кампании."""
        ...

    async def complete_if_running(self, campaign_id: CampaignId, now: datetime) -> bool:
        """Атомарно завершить running-кампанию и вернуть признак перехода."""
        ...


class NotificationTemplateRepository(Protocol):
    """Доступ к логическим шаблонам."""

    async def get(self, key: TemplateKey, version: int | None = None) -> NotificationTemplate | None:
        """Вернуть версию шаблона или последнюю активную, если version не задана."""
        ...

    async def save(self, template: NotificationTemplate) -> None:
        """Создать или обновить версию шаблона."""
        ...

    async def list(
        self,
        status: TemplateStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NotificationTemplate]:
        """Вернуть страницу версий шаблонов с фильтром по статусу."""
        ...

    async def count(self, status: TemplateStatus | None = None) -> int:
        """Вернуть число версий шаблонов с фильтром по статусу."""
        ...

    async def archive_active(
        self,
        key: TemplateKey,
        except_version: int,
        now: datetime,
    ) -> None:
        """Перевести другие активные версии ключа в архив."""
        ...


class DebtorSnapshotRepository(Protocol):
    """Доступ к снимкам должников кампании."""

    async def replace_for_campaign(
        self, campaign_id: CampaignId, snapshots: Sequence[DebtorSnapshot]
    ) -> None:
        """Атомарно заменить снимок должников кампании после полной выгрузки."""
        ...

    async def count(self, campaign_id: CampaignId) -> int:
        """Вернуть число выгруженных должников для проверки полноты."""
        ...

    async def list(self, campaign_id: CampaignId, offset: int, limit: int) -> Sequence[DebtorSnapshot]:
        """Вернуть страницу снимков для создания сообщений."""
        ...


class NotificationMessageRepository(Protocol):
    """Доступ к сообщениям кампании."""

    async def add_many(self, messages: Sequence[NotificationMessage]) -> None:
        """Создать сообщения пачкой, дубли по message_id не создаются."""
        ...

    async def get(self, message_id: MessageId) -> NotificationMessage | None:
        """Вернуть сообщение или None."""
        ...

    async def save(self, message: NotificationMessage) -> None:
        """Сохранить изменения состояния сообщения."""
        ...

    async def list_by_campaign(
        self,
        campaign_id: CampaignId,
        status: MessageStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NotificationMessage]:
        """Вернуть страницу сообщений кампании."""
        ...

    async def count_by_campaign(
        self,
        campaign_id: CampaignId,
        status: MessageStatus | None = None,
    ) -> int:
        """Вернуть число сообщений кампании с фильтром."""
        ...

    async def count_not_terminal(self, campaign_id: CampaignId) -> int:
        """Вернуть число сообщений, которые еще не завершены."""
        ...

    async def cancel_pending(self, campaign_id: CampaignId) -> int:
        """Перевести неотправленные сообщения кампании в cancelled."""
        ...


class MessageAttemptRepository(Protocol):
    """Доступ к результатам попыток отправки."""

    async def add(self, attempt: MessageAttempt) -> None:
        """Добавить запись результата попытки."""
        ...

    async def list_by_message(self, message_id: MessageId) -> Sequence[MessageAttempt]:
        """Вернуть историю попыток сообщения."""
        ...
