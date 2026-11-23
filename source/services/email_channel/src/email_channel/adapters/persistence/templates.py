"""Репозиторий email-шаблонов на SQLAlchemy."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from email_channel.adapters.persistence.models import EmailTemplateRow
from email_channel.domain import EmailTemplate, TemplateKey


class SqlAlchemyEmailTemplateRepository:
    """Хранит канальные варианты шаблонов в схеме email_channel."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def get(
        self,
        key: TemplateKey,
        version: int,
        locale: str | None = None,
    ) -> EmailTemplate | None:
        """Вернуть вариант шаблона или None."""
        statement = select(EmailTemplateRow).where(
            EmailTemplateRow.key == key,
            EmailTemplateRow.version == version,
        )
        if locale is not None:
            statement = statement.where(EmailTemplateRow.locale == locale)
        statement = statement.order_by(EmailTemplateRow.locale).limit(1)
        row = await self._session.scalar(statement)
        return _to_domain(row) if row is not None else None

    async def list(
        self,
        key: TemplateKey | None = None,
        locale: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[EmailTemplate], int]:
        """Вернуть страницу вариантов и общее число."""
        filters = []
        if key is not None:
            filters.append(EmailTemplateRow.key == key)
        if locale is not None:
            filters.append(EmailTemplateRow.locale == locale)
        statement = select(EmailTemplateRow)
        count_statement = select(func.count()).select_from(EmailTemplateRow)
        if filters:
            statement = statement.where(*filters)
            count_statement = count_statement.where(*filters)
        statement = (
            statement.order_by(EmailTemplateRow.key, EmailTemplateRow.version, EmailTemplateRow.locale)
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.scalars(statement)).all()
        total = await self._session.scalar(count_statement)
        return tuple(_to_domain(row) for row in rows), int(total or 0)

    async def save(self, template: EmailTemplate) -> None:
        """Создать или обновить вариант шаблона."""
        statement = (
            pg_insert(EmailTemplateRow)
            .values(
                key=template.key,
                version=template.version,
                locale=template.locale,
                subject_template=template.subject_template,
                html_template=template.html_template,
                plain_text_template=template.plain_text_template,
                required_variables=list(template.required_variables),
                updated_at=template.updated_at,
            )
            .on_conflict_do_update(
                index_elements=["key", "version", "locale"],
                set_={
                    "subject_template": template.subject_template,
                    "html_template": template.html_template,
                    "plain_text_template": template.plain_text_template,
                    "required_variables": list(template.required_variables),
                    "updated_at": template.updated_at,
                },
            )
        )
        await self._session.execute(statement)


def _to_domain(row: EmailTemplateRow) -> EmailTemplate:
    """Преобразовать ORM-строку в доменный шаблон."""
    return EmailTemplate(
        key=TemplateKey(row.key),
        version=row.version,
        locale=row.locale,
        subject_template=row.subject_template,
        html_template=row.html_template,
        plain_text_template=row.plain_text_template,
        required_variables=tuple(row.required_variables or ()),
        updated_at=row.updated_at,
    )
