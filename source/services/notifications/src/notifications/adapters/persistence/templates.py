"""Репозиторий логических шаблонов на SQLAlchemy."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from notifications.adapters.persistence.models import TemplateRow
from notifications.domain import (
    ConflictError,
    NotificationTemplate,
    TemplateKey,
    TemplateStatus,
)


class SqlAlchemyTemplateRepository:
    """Читает и сохраняет версии шаблонов в схеме notification."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def get(
        self,
        key: TemplateKey,
        version: int | None = None,
    ) -> NotificationTemplate | None:
        """Вернуть версию шаблона или последнюю активную."""
        statement = select(TemplateRow).where(TemplateRow.key == key)
        if version is None:
            statement = statement.where(TemplateRow.status == TemplateStatus.ACTIVE.value)
            statement = statement.order_by(TemplateRow.version.desc()).limit(1)
        else:
            statement = statement.where(TemplateRow.version == version)
        row = (await self._session.scalars(statement)).first()
        return None if row is None else _to_domain(row)

    async def save(self, template: NotificationTemplate) -> None:
        """Создать или обновить версию шаблона.

        Raises:
            ConflictError: Версия уже создана или нарушен уникальный активный статус.
        """
        row = await self._session.get(TemplateRow, (template.key, template.version))
        if row is None:
            row = TemplateRow(
                key=template.key,
                version=template.version,
                description=template.description,
                required_variables=list(template.required_variables),
                status=template.status.value,
                created_at=template.created_at,
                updated_at=template.updated_at,
            )
            self._session.add(row)
            try:
                await self._session.flush()
            except IntegrityError as exc:
                raise ConflictError(
                    f"Версия {template.version} шаблона {template.key} уже существует"
                ) from exc
            return
        row.description = template.description
        row.required_variables = list(template.required_variables)
        row.status = template.status.value
        row.updated_at = template.updated_at
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError(
                f"Не удалось сохранить версию {template.version} шаблона {template.key}"
            ) from exc

    async def list(
        self,
        status: TemplateStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NotificationTemplate]:
        """Вернуть страницу версий шаблонов."""
        statement = select(TemplateRow)
        if status is not None:
            statement = statement.where(TemplateRow.status == status.value)
        statement = (
            statement.order_by(TemplateRow.key, TemplateRow.version.desc()).limit(limit).offset(offset)
        )
        rows = (await self._session.scalars(statement)).all()
        return [_to_domain(row) for row in rows]

    async def count(self, status: TemplateStatus | None = None) -> int:
        """Вернуть число версий шаблонов."""
        statement = select(func.count()).select_from(TemplateRow)
        if status is not None:
            statement = statement.where(TemplateRow.status == status.value)
        return int((await self._session.scalar(statement)) or 0)

    async def archive_active(
        self,
        key: TemplateKey,
        except_version: int,
        now: datetime,
    ) -> None:
        """Перевести другие активные версии ключа в архив."""
        statement = (
            update(TemplateRow)
            .where(
                TemplateRow.key == key,
                TemplateRow.status == TemplateStatus.ACTIVE.value,
                TemplateRow.version != except_version,
            )
            .values(status=TemplateStatus.ARCHIVED.value, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        await self._session.execute(statement)


def _to_domain(row: TemplateRow) -> NotificationTemplate:
    """Преобразовать ORM-запись в доменный шаблон."""
    return NotificationTemplate(
        key=TemplateKey(row.key),
        version=row.version,
        description=row.description,
        required_variables=tuple(row.required_variables),
        status=TemplateStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
