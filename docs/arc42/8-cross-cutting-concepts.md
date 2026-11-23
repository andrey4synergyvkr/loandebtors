# 8. Сквозные концепции

Раздел фиксирует концепции, общие для нескольких строительных блоков: доменную
модель и правила хранения строковых констант. Основание: разделы
[4-solution-strategy](4-solution-strategy.md) и
[5-building-block-view](5-building-block-view.md).

## 8.1 Перечень концепций

| №   | Концепция           | Область применения                                      |
|-----|---------------------|---------------------------------------------------------|
| 8.2 | Доменная модель     | Notifications, Scheduler, Email Channel, Audit Exporter |
| 8.3 | Строковые константы | Все сервисы                                             |
| 8.4 | Телеметрия          | Все сервисы и учебный стенд Мониторинга                 |

## 8.2 Доменная модель

Раздел фиксирует словарь предметной области, границы ограниченных контекстов и
формы сообщений между сервисами. Показаны только типы и интерфейсы: имена,
поля, обязательность и допустимые значения. Валидация, переходы состояний,
расчеты и сохранение появятся в коде слоев `domain` и `ports`.

Домен использует только стандартную библиотеку Python и не импортирует FastAPI,
SQLAlchemy, aio-pika, Pydantic, Jinja2 и APScheduler.

### 8.2.1 Общие соглашения и словарь типов

Соглашения:

- value objects объявляются как `@dataclass(frozen=True, slots=True)`;
- сущности объявляются как `@dataclass(slots=True)` и изменяются сценариями приложения;
- статусы и классификаторы объявляются через `StrEnum`, значения совпадают с JSON и БД;
- идентификаторы объявляются через `NewType` над `UUID` или `str`;
- время передается как `datetime` с часовым поясом UTC;
- деньги передаются как `Decimal` и код валюты, арифметика в домене не выполняется;
- коллекции передаются как `tuple` и `Mapping`, изменяемые `list` и `dict` в контрактах не используются.

Общий блок импортов для примеров ниже:

```python
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final, NewType, Protocol
from uuid import UUID
```

Идентификаторы и ключи:

```python
# Идентификатор кампании, первичный ключ агрегата Campaign.
CampaignId = NewType("CampaignId", UUID)
# Идентификатор сообщения и ключ дедупликации при повторной доставке из очереди.
MessageId = NewType("MessageId", UUID)
# Идентификатор audit-события, который создает сервис-источник.
AuditEventId = NewType("AuditEventId", UUID)
# Непрозрачный идентификатор должника из АБС.
DebtorId = NewType("DebtorId", str)
# Номер кредитного договора из АБС.
ContractId = NewType("ContractId", str)
# Логический ключ шаблона без версии.
TemplateKey = NewType("TemplateKey", str)
# Код канала доставки, для v1 используется значение email.
Channel = NewType("Channel", str)
# Ключ создания сообщения из кампании, должника и канала.
IdempotencyKey = NewType("IdempotencyKey", str)

# Единственный реализованный канал в первой версии.
EMAIL_CHANNEL: Final = Channel("email")
```

`DebtorId` и `ContractId` являются непрозрачными идентификаторами АБС.
Внутренние идентификаторы сервисов имеют тип `UUID`.

Значения расписания, денег и результата доставки:

```python
# Денежная сумма. Арифметика в домене не выполняется, значение приходит из АБС.
@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str  # код валюты ISO 4217, например RUB


class ScheduleKind(StrEnum):
    ONE_OFF = "one_off"  # разовый запуск в момент run_at
    CRON = "cron"  # повторяющийся запуск по выражению cron


@dataclass(frozen=True, slots=True)
class ScheduleSpec:
    kind: ScheduleKind
    timezone: str  # часовой пояс IANA, например Europe/Moscow
    run_at: datetime | None = None  # заполняется только для ONE_OFF
    cron: str | None = None  # заполняется только для CRON


class DeliveryOutcome(StrEnum):
    SENT = "sent"  # провайдер принял сообщение
    TRANSIENT_FAILURE = "transient_failure"  # временная ошибка, попытку можно повторить
    PERMANENT_FAILURE = "permanent_failure"  # постоянная ошибка, повторы бессмысленны
    RATE_LIMITED = "rate_limited"  # провайдер ограничил скорость, нужна пауза
```

`Money.currency` содержит код валюты ISO 4217. В `ScheduleSpec` для вида
`ONE_OFF` заполняется `run_at`, для вида `CRON` заполняется `cron`, одновременно
два поля не используются.

Общие порты и ошибки:

```python
class Clock(Protocol):
    # Текущее время в UTC с часовым поясом.
    def now(self) -> datetime: ...


class TransactionManager(Protocol):
    # Граница транзакции, в которой состояние и outbox фиксируются вместе.
    def transaction(self) -> AbstractAsyncContextManager[None]: ...


# В текущей реализации транзакцией управляет UnitOfWork; TransactionManager
# остается контрактом для сценариев, где нужна отдельная граница транзакции.


class DomainError(Exception): ...  # базовое нарушение правил предметной области


class ValidationError(DomainError): ...  # недопустимое значение поля


class InvalidStateError(DomainError): ...  # действие запрещено текущим статусом


class NotFoundError(DomainError): ...  # запрошенный объект отсутствует
```

Общего Python-пакета нет. Каждый сервис объявляет свою копию этих типов.
Совпадение имен и полей поддерживается контрактом обмена
[loandebtors.yaml](../../source/contracts/asyncapi/loandebtors.yaml) и
контрактными тестами.

### 8.2.2 Карта контекстов

- `Notifications`: кампании, логические шаблоны, снимки должников, сообщения и
  попытки. Владеет схемой `notification`.
- `Scheduler`: расписание кампаний и задания APScheduler. Владеет схемой
  `scheduler`.
- `Email Channel`: конфигурация канала, email-варианты шаблонов, отправка и
  попытки. В разделе 5 этот контейнер называется `SMTP Adapter`. Владеет схемой
  `email_channel`.
- `Audit Exporter`: append-only журнал аудита и read-only выгрузка. Владеет
  схемой `audit`.

Граница между контекстами проходит по JSON в RabbitMQ и REST. Прямых импортов
между пакетами сервисов нет. Домен каждого сервиса не знает о типах соседнего
сервиса, на границе используются DTO адаптеров.

### 8.2.3 Контракты обмена

Типы ниже описывают форму сообщений, а не общий модуль. Каждый сервис объявляет
свою копию на границе и маппит ее в доменные типы.

Получатель и команда отправки `message.send`:

```python
@dataclass(frozen=True, slots=True)
class Recipient:
    channel: Channel  # канал, который должен доставить сообщение
    address: str  # адрес в формате канала, для email это почтовый ящик


@dataclass(frozen=True, slots=True)
class NotificationCommand:
    message_id: MessageId  # ключ дедупликации в канальном сервисе
    campaign_id: CampaignId  # связывает команду с кампанией и ее аудитом
    debtor_id: DebtorId  # нужен для трассировки и аудита без обращения к Notifications
    channel: Channel  # канал, который обрабатывает команду
    template_key: TemplateKey  # логический ключ шаблона
    template_version: int  # версия логического шаблона на момент постановки
    variables: Mapping[str, str]  # переменные шаблона, значения приведены к строкам
    recipient: Recipient  # снимок контакта на момент создания сообщения
    idempotency_key: IdempotencyKey  # защита от второго сообщения для той же тройки
```

Поле `template_version` добавлено к составу из раздела 5, чтобы канальный сервис
выбирал точную версию своего варианта шаблона.

События планирования и отмены `campaign.scheduled`, `campaign.cancelled` и
`campaign.start`:

```python
@dataclass(frozen=True, slots=True)
class CampaignScheduled:
    campaign_id: CampaignId  # кампания, которую нужно поставить в расписание
    schedule: ScheduleSpec  # разовый или cron-запуск
    occurred_at: datetime  # время события в UTC


@dataclass(frozen=True, slots=True)
class CampaignCancelled:
    campaign_id: CampaignId  # кампания, которую нужно снять с расписания
    occurred_at: datetime  # время отмены в UTC


@dataclass(frozen=True, slots=True)
class CampaignStart:
    campaign_id: CampaignId  # кампания, которую нужно запустить
    scheduled_for: datetime  # плановое время запуска, для one-off совпадает с run_at
    occurred_at: datetime  # фактическое время публикации события
```

Результаты доставки `message.sent` и `message.failed`:

```python
@dataclass(frozen=True, slots=True)
class MessageSent:
    message_id: MessageId  # сообщение, к которому относится результат
    campaign_id: CampaignId  # для обновления состояния кампании
    channel: Channel  # канал, принявший сообщение
    attempt_number: int  # номер попытки, начиная с 1
    provider_message_id: str | None  # идентификатор письма у провайдера, если вернул
    occurred_at: datetime  # время ответа провайдера


@dataclass(frozen=True, slots=True)
class MessageFailed:
    message_id: MessageId  # сообщение, к которому относится результат
    campaign_id: CampaignId  # для обновления состояния кампании
    channel: Channel  # канал, который не смог доставить сообщение
    attempt_number: int  # номер попытки, начиная с 1
    outcome: DeliveryOutcome  # классификация ошибки
    retryable: bool  # можно ли повторять попытку по правилам канала
    error_code: str | None  # код ошибки провайдера
    error_message: str | None  # описание ошибки без персональных данных
    occurred_at: datetime  # время получения ошибки
```

Событие аудита `audit.event`:

```python
class AuditActorType(StrEnum):
    OPERATOR = "operator"  # сотрудник, управляющий кампанией
    ADMINISTRATOR = "administrator"  # сотрудник, настраивающий канал или выгружающий аудит
    SYSTEM = "system"  # событие сервиса без участия пользователя


@dataclass(frozen=True, slots=True)
class AuditActor:
    type: AuditActorType
    identifier: str | None  # логин сотрудника или имя сервиса, если известны


class AuditOutcome(StrEnum):
    SUCCESS = "success"  # действие завершилось успешно
    FAILURE = "failure"  # действие завершилось ошибкой


class AuditAction(StrEnum):
    # Жизненный цикл кампании.
    CAMPAIGN_CREATED = "campaign.created"
    CAMPAIGN_UPDATED = "campaign.updated"
    CAMPAIGN_SCHEDULED = "campaign.scheduled"
    CAMPAIGN_STARTED = "campaign.started"
    CAMPAIGN_COMPLETED = "campaign.completed"
    CAMPAIGN_CANCELLED = "campaign.cancelled"
    CAMPAIGN_FAILED = "campaign.failed"
    # Логические шаблоны.
    TEMPLATE_CREATED = "template.created"
    TEMPLATE_STATUS_CHANGED = "template.status.changed"
    # Обработка сообщений.
    MESSAGE_QUEUED = "message.queued"
    MESSAGE_SENT = "message.sent"
    MESSAGE_FAILED = "message.failed"
    # Административные действия.
    CHANNEL_CONFIG_UPDATED = "channel.config.updated"
    AUDIT_EXPORTED = "audit.exported"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: AuditEventId  # уникальный идентификатор события
    occurred_at: datetime  # время действия в сервисе-источнике
    service: str  # источник: notifications, scheduler, email_channel или audit_exporter
    actor: AuditActor  # кто выполнил действие
    action: AuditAction  # что произошло
    entity_type: str  # тип сущности: campaign, message или channel
    entity_id: str  # идентификатор сущности в исходном сервисе
    campaign_id: CampaignId | None  # заполняется для событий кампании и сообщений
    message_id: MessageId | None  # заполняется для событий сообщений
    channel: Channel | None  # заполняется для событий канала
    outcome: AuditOutcome  # результат действия
    details: Mapping[str, str]  # дополнительные поля, уже без персональных данных
    correlation_id: str  # связывает события одного сценария
    trace_id: str | None  # идентификатор OTel-трейса, если он есть


class AuditEventOutbox(Protocol):
    # Пишет событие в outbox в транзакции сервиса, без публикации в RabbitMQ.
    async def add(self, event: AuditEvent) -> None: ...
```

`details` содержит только строковые значения, уже очищенные от персональных
данных. Поле `service` принимает значения `notifications`, `scheduler`,
`email_channel` и `audit_exporter`; новые сервисы добавляют свои имена без
изменения формы.

### 8.2.4 Notifications

Статусы:

```python
class CampaignStatus(StrEnum):
    DRAFT = "draft"  # создана, выборка и запуск не выполнялись
    SCHEDULED = "scheduled"  # ожидает запуска по расписанию
    RUNNING = "running"  # кампания запущена, идет выгрузка, создание и отправка сообщений
    COMPLETED = "completed"  # все сообщения обработаны
    CANCELLED = "cancelled"  # остановлена оператором
    FAILED = "failed"  # выборка или запуск завершились ошибкой


class TemplateStatus(StrEnum):
    DRAFT = "draft"  # еще не используется кампаниями
    ACTIVE = "active"  # доступен для новых кампаний
    ARCHIVED = "archived"  # сохранен для истории, новые отправки не используют


class MessageStatus(StrEnum):
    PENDING = "pending"  # ожидает постановки в очередь
    QUEUED = "queued"  # команда опубликована в message.send
    SENT = "sent"  # провайдер принял письмо, факт доставки не подтвержден
    FAILED = "failed"  # постоянная ошибка или исчерпаны попытки
    CANCELLED = "cancelled"  # отменено из-за остановки кампании
```

`CampaignStatus.FAILED` используется, когда выборка или запуск завершились
ошибкой. `MessageStatus.CANCELLED` выставляется сообщениям, которые не были
отправлены из-за остановки кампании.

Кампания и параметры выборки:

```python
@dataclass(frozen=True, slots=True)
class DebtorSelection:
    criteria: Mapping[str, str]  # параметры выборки для АБС, состав ключей задает контракт АБС


@dataclass(slots=True)
class Campaign:
    id: CampaignId  # идентификатор кампании
    name: str  # человекочитаемое имя для оператора
    channel: Channel  # канал рассылки, в v1 всегда email
    template_key: TemplateKey  # выбранный логический шаблон
    template_version: int  # зафиксированная версия шаблона
    status: CampaignStatus  # текущее состояние жизненного цикла
    selection: DebtorSelection  # параметры выгрузки из АБС
    schedule: ScheduleSpec | None  # None означает немедленный запуск
    selected_debtors: int  # сколько должников фактически выгружено
    selection_expected: int | None  # сколько ожидалось по данным АБС, для проверки полноты
    selection_completed_at: datetime | None  # время успешного завершения выгрузки
    messages_created_at: datetime | None  # время завершения создания сообщений
    created_at: datetime
    updated_at: datetime
    scheduled_at: datetime | None  # время постановки в расписание
    started_at: datetime | None  # время фактического старта
    finished_at: datetime | None  # время завершения или окончательной остановки
    cancelled_at: datetime | None  # время отмены оператором
    failure_reason: str | None  # причина статуса FAILED
```

`schedule = None` означает немедленный запуск. Заполненное расписание передается
в `campaign.scheduled`.

Кампания создается в статусе `draft` с выбранной версией шаблона. Версия должна
существовать и быть активной; в первой версии канал только `email`. Изменять
можно только `draft`-кампанию, а ключ и версия шаблона в запросе передаются
вместе. Создание и изменение пишут audit-события `campaign.created` и
`campaign.updated` в транзакционный outbox.

Планирование переводит `draft` в `scheduled` и принимает разовое расписание с
`run_at` в будущем или cron-выражение из пяти полей. Отмена переводит
`scheduled` в `cancelled` и заполняет `cancelled_at` и `finished_at`. Оба
действия пишут одноименные audit-события, а также `campaign.scheduled` или
`campaign.cancelled` в outbox для Scheduler.

Немедленный запуск переводит `draft` в `running` и пишет `campaign.start` в
outbox собственной очереди. Потребитель `campaign.start` выгружает все страницы
АБС, проверяет стабильность `total`, уникальность `debtor_id`, совпадение
количества с `total` и лимит 10 000, после чего в одной транзакции сохраняет
снимки должников, создает сообщения и команды `message.send`. Частичные снимки
не сохраняются. Параллельная обработка защищена advisory-блокировкой, временные
ошибки АБС повторяются через retry-очередь, постоянные переводят кампанию в
`failed`. Отмена выполняющейся кампании переводит неотправленные сообщения в
`cancelled`, а завершение всех сообщений переводит кампанию в `completed` и
пишет `campaign.completed` со счетчиками результатов.

`DebtorSelection.criteria` остается непрозрачным набором строк в домене.
Адаптер запуска отображает известные ключи `min_days_overdue`,
`max_days_overdue` и `channel` в query-параметры АБС, а неизвестные ключи
игнорирует с предупреждением.

Логический шаблон:

```python
@dataclass(slots=True)
class NotificationTemplate:
    key: TemplateKey  # логический ключ, общий для всех каналов
    version: int  # версия логического шаблона
    description: str  # назначение шаблона для оператора
    required_variables: tuple[str, ...]  # переменные, без которых рендеринг невозможен
    status: TemplateStatus  # доступность для новых кампаний
    created_at: datetime
    updated_at: datetime
```

Логический шаблон не содержит текста письма. Версия фиксируется в кампании и в
`NotificationCommand`, чтобы отправка оставалась воспроизводимой после изменения
шаблона. Кампания ссылается на активную версию, архивированные версии для новых
отправок не используются. У одного ключа может быть только одна активная версия:
активация новой версии переводит предыдущую в `archived`. Разрешены переходы
`draft -> active`, `draft -> archived` и `active -> archived`; `archived`
окончателен. Создание версии и смена статуса пишут audit-события
`template.created` и `template.status.changed` в транзакционный outbox.
Изменение настроек SMTP-адаптера в Email Channel пишет
`channel.config.updated` в outbox схемы `email_channel`.

Данные должника из АБС:

```python
@dataclass(frozen=True, slots=True)
class DebtorContact:
    channel: Channel  # канал, к которому относится адрес
    address: str  # адрес в формате канала
    is_primary: bool  # основной контакт для этого канала


@dataclass(frozen=True, slots=True)
class DebtSummary:
    contract_id: ContractId  # номер договора из АБС
    amount: Money  # сумма к погашению по данным АБС
    due_date: date  # плановая дата погашения
    days_overdue: int  # количество дней просрочки на момент выгрузки


@dataclass(frozen=True, slots=True)
class AbsDebtor:
    debtor_id: DebtorId  # идентификатор должника в АБС
    full_name: str  # имя для персонализации, в аудит не пишется
    contacts: tuple[DebtorContact, ...]  # контакты по каналам
    debts: tuple[DebtSummary, ...]  # задолженности на момент выгрузки


@dataclass(frozen=True, slots=True)
class AbsDebtorPage:
    items: tuple[AbsDebtor, ...]  # должники текущей страницы
    page: int  # номер страницы, начиная с 1
    total: int  # общее число должников по выборке
    has_next: bool  # есть ли следующая страница


@dataclass(frozen=True, slots=True)
class DebtorSnapshot:
    campaign_id: CampaignId  # кампания, для которой сохранен снимок
    debtor: AbsDebtor  # данные должника на момент выгрузки
    fetched_at: datetime  # время получения страницы из АБС
```

Сообщение и результат попытки:

```python
@dataclass(slots=True)
class NotificationMessage:
    id: MessageId  # идентификатор сообщения и ключ дедупликации
    campaign_id: CampaignId  # кампания-владелец
    debtor_id: DebtorId  # должник-получатель
    channel: Channel  # канал доставки
    template_key: TemplateKey  # логический шаблон
    template_version: int  # версия шаблона на момент создания сообщения
    variables: Mapping[str, str]  # снимок переменных для повторной отправки
    recipient: Recipient  # снимок получателя на момент создания
    idempotency_key: IdempotencyKey  # защита от дубля campaign + debtor + channel
    status: MessageStatus  # текущее состояние
    attempt_count: int  # сколько попыток уже завершилось
    max_attempts: int  # предел попыток для этого сообщения
    created_at: datetime
    queued_at: datetime | None  # время первой публикации в message.send
    last_attempt_at: datetime | None  # время последней попытки
    sent_at: datetime | None  # время ответа провайдера об успехе
    failed_at: datetime | None  # время окончательного отказа
    next_attempt_at: datetime | None  # плановое время следующей попытки
    last_error_code: str | None  # последний код ошибки провайдера
    last_error_message: str | None  # последнее описание ошибки без персональных данных


@dataclass(frozen=True, slots=True)
class MessageAttempt:
    message_id: MessageId  # сообщение, к которому относится попытка
    attempt_number: int  # номер попытки, начиная с 1
    outcome: DeliveryOutcome  # результат попытки
    occurred_at: datetime  # время получения результата
    provider_message_id: str | None  # идентификатор письма у провайдера
    provider_error_code: str | None  # код ошибки провайдера
```

`variables` содержит значения, приведенные к строкам. Форматирование и подстановку
выполняет канальный сервис. Если у должника несколько задолженностей, сумма
`amount` складывается по всем долгам, `currency` и `contract_id` берутся из
первого долга, `due_date` выбирается минимальная, а `days_overdue` максимальная.
`MessageAttempt` фиксирует результат, полученный из `message.sent` или
`message.failed`; детали собственной отправки хранятся в Email Channel.

Успешный результат переводит сообщение в `sent`. Временная ошибка возвращает
его в `queued`, заполняет `next_attempt_at` и пишет отложенный `message.send` в
outbox с `available_at` из `next_attempt_at`; задержка растет экспоненциально.
Постоянная ошибка или исчерпание попыток переводит сообщение в `failed`.
Результат по отмененному сообщению и повторная доставка результата игнорируются.

Порты Notifications:

```python
class CampaignRepository(Protocol):
    # Создает новую кампанию.
    async def add(self, campaign: Campaign) -> None: ...
    # Возвращает кампанию или None.
    async def get(self, campaign_id: CampaignId) -> Campaign | None: ...
    # Сохраняет изменения существующей кампании.
    async def save(self, campaign: Campaign) -> None: ...
    # Возвращает страницу кампаний с фильтром по статусу.
    async def list(
        self, status: CampaignStatus | None = None, limit: int = 50, offset: int = 0
    ) -> Sequence[Campaign]: ...
    # Возвращает число кампаний с фильтром по статусу.
    async def count(self, status: CampaignStatus | None = None) -> int: ...
    # Пытается взять транзакционную advisory-блокировку обработки кампании.
    async def try_advisory_lock(self, campaign_id: CampaignId) -> bool: ...
    # Атомарно завершает running-кампанию и возвращает признак перехода.
    async def complete_if_running(self, campaign_id: CampaignId, now: datetime) -> bool: ...


class NotificationTemplateRepository(Protocol):
    # Возвращает версию шаблона или последнюю активную, если version не задана.
    async def get(self, key: TemplateKey, version: int | None = None) -> NotificationTemplate | None: ...
    # Создает или обновляет версию шаблона.
    async def save(self, template: NotificationTemplate) -> None: ...
    # Возвращает страницу версий с фильтром по статусу.
    async def list(
        self, status: TemplateStatus | None = None, limit: int = 50, offset: int = 0
    ) -> Sequence[NotificationTemplate]: ...
    # Возвращает число версий с фильтром по статусу.
    async def count(self, status: TemplateStatus | None = None) -> int: ...
    # Переводит другие активные версии ключа в архив.
    async def archive_active(self, key: TemplateKey, except_version: int, now: datetime) -> None: ...


class DebtorSnapshotRepository(Protocol):
    # Атомарно заменяет снимок должников кампании после полной выгрузки.
    async def replace_for_campaign(
        self, campaign_id: CampaignId, snapshots: Sequence[DebtorSnapshot]
    ) -> None: ...
    # Возвращает число выгруженных должников для проверки полноты.
    async def count(self, campaign_id: CampaignId) -> int: ...
    # Возвращает страницу снимков для создания сообщений.
    async def list(self, campaign_id: CampaignId, offset: int, limit: int) -> Sequence[DebtorSnapshot]: ...


class NotificationMessageRepository(Protocol):
    # Создает сообщения пачкой, дубли по message_id не создаются.
    async def add_many(self, messages: Sequence[NotificationMessage]) -> None: ...
    # Возвращает сообщение или None.
    async def get(self, message_id: MessageId) -> NotificationMessage | None: ...
    # Сохраняет изменения состояния сообщения.
    async def save(self, message: NotificationMessage) -> None: ...
    # Возвращает страницу сообщений кампании для мониторинга и возобновления.
    async def list_by_campaign(
        self,
        campaign_id: CampaignId,
        status: MessageStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NotificationMessage]: ...
    # Возвращает число сообщений кампании с фильтром.
    async def count_by_campaign(
        self, campaign_id: CampaignId, status: MessageStatus | None = None
    ) -> int: ...
    # Возвращает число незавершенных сообщений кампании.
    async def count_not_terminal(self, campaign_id: CampaignId) -> int: ...
    # Переводит неотправленные сообщения кампании в cancelled.
    async def cancel_pending(self, campaign_id: CampaignId) -> int: ...


class MessageAttemptRepository(Protocol):
    # Добавляет запись о результате попытки.
    async def add(self, attempt: MessageAttempt) -> None: ...
    # Возвращает историю попыток сообщения.
    async def list_by_message(self, message_id: MessageId) -> Sequence[MessageAttempt]: ...


class AbsDebtorSource(Protocol):
    # Возвращает одну страницу выгрузки АБС, нумерация страниц начинается с 1.
    async def fetch_page(self, page: int, page_size: int, debtor_filter: DebtorFilter) -> AbsDebtorPage: ...


class CampaignEventOutbox(Protocol):
    # Записывает campaign.scheduled в транзакционный outbox.
    async def add_scheduled(
        self, event: CampaignScheduled, correlation_id: str, trace_id: str | None
    ) -> None: ...
    # Записывает campaign.cancelled в транзакционный outbox.
    async def add_cancelled(
        self, event: CampaignCancelled, correlation_id: str, trace_id: str | None
    ) -> None: ...
    # Записывает campaign.start в транзакционный outbox.
    async def add_start(self, event: CampaignStart, correlation_id: str, trace_id: str | None) -> None: ...


class MessageCommandOutbox(Protocol):
    # Записывает команду message.send в транзакционный outbox.
    async def add(
        self,
        command: NotificationCommand,
        correlation_id: str,
        trace_id: str | None,
        occurred_at: datetime | None = None,
        available_at: datetime | None = None,
    ) -> None: ...
```

`MessageCommandOutbox` заменяет отдельный publisher: команда `message.send`
публикуется через outbox relay. Порт `NotificationCommandPublisher` остается
объявленным для прямой публикации, но в текущем сценарии не вызывается.
`AbsDebtorSource` вызывает АБС методом pull.
Постраничная выгрузка продолжается до `has_next = false`, после чего
`selected_debtors` сравнивается с `selection_expected`. Контракт ответа
зафиксирован в `source/contracts/openapi/abs.yaml`, на стенде его реализует
заглушка `abs`. `Clock` и `AuditEventOutbox` используются из разделов 8.2.1 и
8.2.3, транзакцией управляет `UnitOfWork`.

### 8.2.5 Scheduler

```python
class ScheduleStatus(StrEnum):
    ACTIVE = "active"  # задание зарегистрировано и будет запущено
    PAUSED = "paused"  # задание временно не запускается
    CANCELLED = "cancelled"  # задание снято, кампания отменена
    COMPLETED = "completed"  # разовое задание выполнено


@dataclass(slots=True)
class CampaignSchedule:
    campaign_id: CampaignId  # кампания, которой принадлежит расписание
    schedule: ScheduleSpec  # правило запуска
    status: ScheduleStatus  # состояние задания
    next_run_at: datetime | None  # ближайший плановый запуск, None для снятого задания
    last_triggered_at: datetime | None  # время последнего срабатывания
    correlation_id: str | None  # корреляция исходной команды campaign.scheduled
    created_at: datetime
    updated_at: datetime
```

`CampaignSchedule` не хранит идентификатор задания APScheduler. Адаптер строит
его детерминированно из `campaign_id`, поэтому домен не зависит от библиотеки.

Порты Scheduler:

```python
class CampaignScheduleRepository(Protocol):
    # Возвращает расписание кампании или None.
    async def get(self, campaign_id: CampaignId) -> CampaignSchedule | None: ...
    # Создает или обновляет расписание.
    async def save(self, schedule: CampaignSchedule) -> None: ...
    # Возвращает активные расписания для восстановления заданий после перезапуска.
    async def list_active(self) -> Sequence[CampaignSchedule]: ...


class CancelledCampaignRepository(Protocol):
    # Идемпотентно сохраняет отметку об отмене кампании.
    async def add(self, campaign_id: CampaignId, occurred_at: datetime) -> None: ...
    # Возвращает время отмены или None.
    async def get_occurred_at(self, campaign_id: CampaignId) -> datetime | None: ...


# Вызывается планировщиком при срабатывании задания.
type JobCallback = Callable[[CampaignId], Awaitable[None]]


class JobRegistrar(Protocol):
    # Проверяет расписание до регистрации.
    async def validate(self, schedule: ScheduleSpec) -> None: ...
    # Идемпотентно регистрирует задание и возвращает next_run_at.
    async def register(
        self, schedule: CampaignSchedule, callback: JobCallback
    ) -> datetime | None: ...
    # Возвращает ближайший запуск задания.
    async def next_run_at(self, campaign_id: CampaignId) -> datetime | None: ...
    # Снимает задание, если оно существует.
    async def remove(self, campaign_id: CampaignId) -> None: ...
```

`JobRegistrar` является портом к APScheduler. Реализация использует
MemoryJobStore, а источником истины служит `CampaignSchedule` в PostgreSQL;
активные расписания восстанавливаются при старте, misfire и coalesce берутся из
конфигурации сервиса. `campaign.start` публикуется через outbox, отдельный порт
`CampaignStartPublisher` не выделен. Отметка `cancelled_campaign`
защищает от порядка `campaign.cancelled` раньше `campaign.scheduled`.

`campaign.start` и audit-события записываются в outbox схемы `scheduler` в одной
транзакции с изменением `CampaignSchedule`. Отмена запланированной кампании
приходит событием `campaign.cancelled` в очередь `scheduler.commands`.

### 8.2.6 Email Channel

Значения канала:

```python
@dataclass(frozen=True, slots=True)
class EmailAddress:
    value: str  # адрес вида local@domain, нормализация выполняется позже


# Имя секрета, а не его значение.
SecretRef = NewType("SecretRef", str)


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    host: str  # SMTP-хост провайдера
    port: int  # порт SMTP, обычно 587 для STARTTLS
    username: str  # учетная запись провайдера
    password_ref: SecretRef  # ссылка на пароль, сам пароль в домене не хранится
    from_address: EmailAddress  # адрес отправителя
    from_name: str  # отображаемое имя отправителя
    use_starttls: bool  # включает STARTTLS перед отправкой
    timeout_seconds: float  # таймаут SMTP-операции
    rate_limit_per_second: int  # глобальный лимит писем в секунду
    enabled: bool  # выключенный канал не принимает новые отправки
    updated_at: datetime  # время последнего изменения настроек
```

`SmtpConfig` хранит ссылку на секрет, а не пароль. Значение секрета получает
порт `SecretsProvider` во время отправки.

Email-вариант шаблона и результат рендеринга:

```python
@dataclass(slots=True)
class EmailTemplate:
    key: TemplateKey  # логический ключ, общий с Notifications
    version: int  # версия канального варианта
    locale: str  # язык и регион, например ru-RU
    subject_template: str  # Jinja2-шаблон темы
    html_template: str  # Jinja2-шаблон HTML-части
    plain_text_template: str  # Jinja2-шаблон текстовой части
    required_variables: tuple[str, ...]  # переменные, обязательные для этого варианта
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    recipient: EmailAddress  # получатель письма
    subject: str  # готовая тема после рендеринга
    html_body: str  # готовое HTML-тело
    plain_text_body: str  # готовое текстовое тело
```

Попытка отправки и результат порта отправки:

```python
@dataclass(frozen=True, slots=True)
class SendAttempt:
    message_id: MessageId  # сообщение из входящей команды
    attempt_number: int  # номер попытки, начиная с 1
    recipient: EmailAddress  # фактический получатель
    started_at: datetime
    finished_at: datetime | None  # None, пока попытка выполняется
    outcome: DeliveryOutcome | None  # None, пока попытка выполняется
    provider_message_id: str | None  # идентификатор письма у провайдера
    provider_error_code: str | None  # код ошибки провайдера
    provider_error_message: str | None  # описание ошибки без персональных данных


@dataclass(frozen=True, slots=True)
class SendReceipt:
    provider_message_id: str | None  # идентификатор письма у провайдера, если вернул
    accepted_at: datetime  # время приема письма провайдером


@dataclass(frozen=True, slots=True)
class SendFailure:
    outcome: DeliveryOutcome  # TRANSIENT_FAILURE, PERMANENT_FAILURE или RATE_LIMITED
    provider_error_code: str | None  # код ошибки провайдера
    provider_error_message: str | None  # описание ошибки без персональных данных


# SendReceipt означает успех, SendFailure означает ошибку с классификацией.
type SendResult = SendReceipt | SendFailure
```

Порты Email Channel:

```python
class ChannelConfigRepository(Protocol):
    # Возвращает настройки канала или None, если канал еще не настроен.
    async def get(self) -> SmtpConfig | None: ...
    # Создает или обновляет настройки канала.
    async def save(self, config: SmtpConfig) -> None: ...


class EmailTemplateRepository(Protocol):
    # Возвращает вариант шаблона по ключу, версии и локали.
    async def get(
        self, key: TemplateKey, version: int, locale: str | None = None
    ) -> EmailTemplate | None: ...
    # Возвращает страницу вариантов и общее число.
    async def list(
        self,
        key: TemplateKey | None = None,
        locale: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[EmailTemplate], int]: ...
    # Создает или обновляет вариант шаблона.
    async def save(self, template: EmailTemplate) -> None: ...


class ProcessedMessageRepository(Protocol):
    # Проверяет, обработано ли сообщение.
    async def is_processed(self, message_id: MessageId) -> bool: ...
    # Отмечает сообщение обработанным и возвращает True при первой обработке.
    async def mark_processed(self, message_id: MessageId, processed_at: datetime) -> bool: ...


class SendAttemptRepository(Protocol):
    # Добавляет запись о попытке отправки.
    async def add(self, attempt: SendAttempt) -> None: ...
    # Возвращает число завершенных попыток сообщения.
    async def count_by_message(self, message_id: MessageId) -> int: ...


class EmailRenderer(Protocol):
    # Чистая операция без сети: подставляет переменные в шаблон.
    def render(
        self,
        template: EmailTemplate,
        variables: Mapping[str, str],
        recipient: EmailAddress,
    ) -> RenderedEmail: ...


class EmailSender(Protocol):
    # Единственная сетевая операция канала, ошибка возвращается как SendFailure.
    async def send(
        self,
        config: SmtpConfig,
        email: RenderedEmail,
        password: str,
    ) -> SendResult: ...


class RateLimiter(Protocol):
    # Применяет лимит из настроек канала.
    def configure(self, rate_per_second: int) -> None: ...
    # Ждет свободный слот глобального лимита канала.
    async def acquire(self) -> None: ...


class SecretsProvider(Protocol):
    # Возвращает значение секрета по ссылке во время отправки.
    async def get(self, ref: SecretRef) -> str: ...


class SmtpProbe(Protocol):
    # Проверяет TCP-доступность SMTP-хоста.
    async def check(self, host: str, port: int, timeout_seconds: float) -> str | None: ...


class MessageResultOutbox(Protocol):
    # Записывает message.sent в транзакционный outbox.
    async def add_sent(
        self, event: MessageSent, correlation_id: str, trace_id: str | None
    ) -> None: ...
    # Записывает message.failed в транзакционный outbox.
    async def add_failed(
        self, event: MessageFailed, correlation_id: str, trace_id: str | None
    ) -> None: ...
```

`EmailRenderer` реализуется адаптером Jinja2, домен знает только интерфейс.
`RateLimiter` является глобальным для канала и опирается на
`rate_limit_per_second` из конфигурации. `SendAttempt` хранит детали собственной
отправки, а `MessageAttempt` в Notifications хранит результат, полученный из
очереди. Входящая команда `message.send` описана в разделе 8.2.3; домен канала
не импортирует типы Notifications. `Clock` и `AuditEventOutbox` используются из
разделов 8.2.1 и 8.2.3, транзакцией управляет `UnitOfWork`.

### 8.2.7 Audit Exporter

```python
@dataclass(frozen=True, slots=True)
class AuditRecord:
    sequence: int  # порядковый номер записи в журнале, назначает хранилище
    event: AuditEvent  # исходное событие без изменений
    ingested_at: datetime  # время записи в журнал


@dataclass(frozen=True, slots=True)
class AuditFilter:
    campaign_id: CampaignId | None = None  # фильтр по кампании
    channel: Channel | None = None  # фильтр по каналу
    action: AuditAction | None = None  # фильтр по действию
    occurred_from: datetime | None = None  # нижняя граница occurred_at, включительно
    occurred_to: datetime | None = None  # верхняя граница occurred_at, не включительно
    cursor: str | None = None  # курсор следующей страницы
    limit: int = 100  # размер страницы


@dataclass(frozen=True, slots=True)
class AuditPage:
    items: tuple[AuditRecord, ...]  # записи текущей страницы
    next_cursor: str | None  # курсор следующей страницы или None


class AuditStore(Protocol):
    # Только добавление, без изменения и удаления записей.
    async def append(self, event: AuditEvent) -> None: ...
    # Чтение с фильтрами и курсором.
    async def query(self, filters: AuditFilter) -> AuditPage: ...
    # Чтение одной записи по идентификатору события для Audit Export API.
    async def get_by_event_id(self, event_id: AuditEventId) -> AuditRecord | None: ...
```

`sequence` присваивается при записи и задает порядок журнала. В порту `AuditStore`
нет методов изменения и удаления, append-only выражен на уровне интерфейса.
Событие `audit.event` описано в разделе 8.2.3.

### 8.2.8 Границы модели

- Одна кампания содержит не более 10 000 уникальных должников. В v1 одному
  должнику соответствует одно сообщение электронной почты.
- Кампания запускается только после полной выгрузки выборки из АБС. Частичная
  выборка не допускается, при недоступности АБС кампания не запускается.
- `message_id` дедуплицирует повторную доставку одного и того же сообщения из
  очереди. `idempotency_key` строится из кампании, должника и канала и не
  позволяет создать второе сообщение для той же тройки.
- `MessageStatus.SENT` означает, что провайдер принял письмо. Факт доставки в
  почтовый ящик в v1 не подтверждается и отдельным статусом не моделируется.
- `DeliveryOutcome` различает успех, временную ошибку, постоянную ошибку и
  ограничение скорости. Временные ошибки повторяются, постоянные завершают
  попытки. Счетчик попыток и `next_attempt_at` хранятся в сообщении, механизм
  задержки остается в инфраструктуре.
- `AuditStore` предоставляет только добавление и чтение. `AuditEvent.details`
  содержит маскированные значения, полные адреса электронной почты и имена в
  аудит не попадают.
- Рендеринг выполняет канальный сервис. `NotificationCommand` несет
  `template_key`, версию и переменные, готового текста в команде нет.
- Кампания v1 использует один канал. Мультиканальная кампания и несколько
  сообщений на должника не моделируются.
- Задолженность не рассчитывается и не изменяется. `DebtSummary` является
  снимком данных АБС на момент выборки.
- Домен не импортирует FastAPI, SQLAlchemy, aio-pika, Pydantic, Jinja2 и
  APScheduler. Порты объявляются через `Protocol`.

### 8.2.9 Открытые вопросы

- Критерии выборки и поля ответа АБС зафиксированы в
  `source/contracts/openapi/abs.yaml`: `min_days_overdue`, `max_days_overdue`,
  `channel` и `AbsDebtorPage`. Заглушка `abs` реализует этот контракт на
  стенде.
- Несколько задолженностей у должника. `AbsDebtor.debts` допускает несколько
  записей, правила формирования переменных для шаблона не определены.
- Подтверждение доставки. Провайдер в v1 не дает надежного факта доставки,
  статус `sent` означает прием письма.
- Секрет SMTP. `SmtpConfig.password_ref` хранит ссылку, а не пароль, способ
  хранения ссылки определит реализация.
- Расширение `AuditAction`. Новые действия добавляются значениями перечисления
  без изменения формы `AuditEvent`.

## 8.3 Строковые константы

Строковые литералы, которые используются в сравнениях, ключах словарей,
сообщениях, ответах и контрактах, не разбрасываются по коду. Для них заводится
одна точка объявления в том слое, который владеет этим словарем.

### 8.3.1 Что считается константой

- имена событий и routing keys: `campaign.scheduled`, `campaign.cancelled`,
  `campaign.start`, `message.send`, `audit.event`;
- имена очередей и exchange: `scheduler.commands`, `notification.commands`,
  `loan-debtors.events`;
- заголовки сообщений и HTTP: `traceparent`, `Idempotency-Key`;
- коды ошибок, типы `Problem` и машинные коды ответов;
- статусы, действия аудита, коды каналов и другие закрытые наборы значений;
- ключи шаблонов, имена метрик, имена переменных окружения и полей конфигурации;
- префиксы путей API и версии контрактов.

Закрытый набор значений оформляется через `StrEnum`. Открытый словарь или
одиночное значение оформляется через `Final[str]`.

### 8.3.2 Где хранить

| Словарь                                      | Слой                          | Пример                            |
|----------------------------------------------|-------------------------------|-----------------------------------|
| Статусы, действия, коды каналов              | `domain`                      | `domain/enums.py`                 |
| Имена проверок health и пояснения            | `application`                 | `application/health.py`           |
| События, очереди, routing keys               | `adapters`                    | `adapters/messaging/constants.py` |
| HTTP-пути, заголовки, теги                   | `adapters`                    | `adapters/http/constants.py`      |
| Типы `Problem`, коды ошибок, media type      | `adapters`                    | `adapters/http/problems.py`       |
| Переменные окружения, метрики, логи          | `config.py`, `infrastructure` | `config.py`, `infrastructure/logging.py` |

Общего модуля констант на все сервисы нет. Каждый сервис хранит свой словарь в
своем пакете, как и доменные типы. Централизация выполняется по слою и
назначению, а не одним общим файлом на все случаи. Совпадение значений с
AsyncAPI и OpenAPI проверяется контрактными тестами.

### 8.3.3 Правила использования

- сравнение, ключи словарей, формирование событий и ответов используют константу, а не литерал;
- один и тот же литерал не дублируется в нескольких модулях;
- значение константы совпадает с контрактом, БД и внешним API;
- изменение значения начинается с изменения контракта;
- одноразовые человекочитаемые сообщения логов и пояснений могут оставаться литералами, если не участвуют в сравнениях и не повторяются;
- тесты проверяют внешние значения, поэтому в контрактных тестах литерал допустим осознанно, в остальных тестах лучше использовать константу.

Пример:

```python
from enum import StrEnum
from typing import Final

NOT_IMPLEMENTED_TYPE: Final = "urn:loandebtors:error:not-implemented"
NOT_IMPLEMENTED_CODE: Final = "not_implemented"


class NotificationEvent(StrEnum):
    CAMPAIGN_SCHEDULED = "campaign.scheduled"
    MESSAGE_SEND = "message.send"
    AUDIT_EVENT = "audit.event"
```

Плохо:

```python
if action == "message.sent":
    ...
```

Хорошо:

```python
if action == AuditAction.MESSAGE_SENT:
    ...
```

## 8.4 Телеметрия

Раздел фиксирует провайдеры OpenTelemetry, формат экспорта и состав учебной
системы Мониторинга. Основание: TC-5, QG-4 и раздел
[4-solution-strategy](4-solution-strategy.md). Телеметрия является
сквозной концепцией: её используют все сервисы, но конкретный бэкенд
Мониторинга не влияет на домен и бизнес-логику.

### 8.4.1 Провайдеры SDK

| Провайдер                       | Назначение     | Состав                                                                 |
|---------------------------------|----------------|------------------------------------------------------------------------|
| `TracerProvider`                | Трейсы         | `BatchSpanProcessor` и `OTLPSpanExporter` по gRPC                      |
| `MeterProvider`                 | Метрики        | `PeriodicExportingMetricReader` и `OTLPMetricExporter` по gRPC         |
| `LoggerProvider`                | Логи           | `BatchLogRecordProcessor`, `OTLPLogExporter` и `LoggingHandler`        |
| `Resource`                      | Атрибуты       | `service.name`, `service.version`, `deployment.environment`, `service.instance.id` |
| `TextMapPropagator`             | Контекст       | Композитный W3C Trace Context и W3C Baggage                            |
| `Sampler`                       | Сэмплирование  | `ParentBased(TraceIdRatioBased(ratio))`                                |

`OTLPSpanExporter`, `OTLPMetricExporter` и `OTLPLogExporter` используют
gRPC-эндпоинт `OTLP_ENDPOINT`. Логи одновременно пишутся JSON в stdout по
CV-5 и отправляются в OTel. В локальной среде допускается
`OTEL_INSECURE=true`, в промышленной среде TLS обязателен. Экспорт телеметрии
не является критичной зависимостью: при недоступности коллектора сервис
продолжает обрабатывать запросы, а ошибки экспорта попадают в лог.

### 8.4.2 Атрибуты, контекст и сэмплирование

Каждый сервис передаёт в `Resource` четыре атрибута: имя сервиса, версию
пакета, имя среды и идентификатор экземпляра процесса. Идентификатор
экземпляра создаётся заново при старте процесса и не используется как метка
метрик с высокой кардинальностью.

Контекст распространяется по W3C Trace Context. В HTTP используется заголовок
`traceparent`, в RabbitMQ заголовки `traceparent` и `correlation_id`. Это
позволяет связать вызов АБС, публикацию `message.send`, обработку результата
доставки и запись аудита в один трейс. Логи получают `trace_id` и `span_id` из
активного спана, поэтому запись в Loki открывается в Tempo по ссылке.

Доля сэмплируемых трейсов задаётся переменной `OTEL_SAMPLE_RATIO` от 0 до 1.
Для локального стенда допустимо значение `1.0`, для нагрузочного прогона на
10 000 сообщений рекомендуется `0.1`. Метрики сэмплированием не управляются:
агрегация выполняется SDK и экспортируется целиком. Логи не сэмплируются на
стороне SDK, их объём ограничивается уровнем логирования и retention Loki.

### 8.4.3 Система Мониторинга на учебном стенде

| Компонент             | Роль                                                     | Порт             |
|-----------------------|----------------------------------------------------------|------------------|
| OTel Collector Contrib| Приём OTLP, batch, memory limiter, маршрутизация          | 4317, 4318, 8888, 8889 |
| Grafana Tempo         | Хранение и поиск трейсов                                 | 3200             |
| Grafana Loki          | Хранение и поиск логов                                   | 3100             |
| Prometheus            | Хранение метрик и scrape коллектора                      | 9090             |
| Grafana               | UI, дашборды, Explore для метрик, трейсов и логов        | 3000             |

Поток данных:

1. Сервис отправляет трейсы, метрики и логи по OTLP gRPC в OTel Collector.
2. Collector отправляет трейсы в Tempo через OTLP exporter.
3. Collector отдаёт метрики через `prometheus` exporter на порту 8889.
4. Collector отправляет логи в Loki через OTLP HTTP exporter.
5. Prometheus забирает метрики с коллектора.
6. Grafana читает Tempo, Loki и Prometheus и показывает все виды данных.

Коллектор является единственной точкой интеграции с Мониторингом. При смене
бэкенда меняется конфигурация коллектора, а код сервисов и SDK-провайдеры
остаются прежними. Платформы SaaS и выделенные кластеры на стенде не
используются по OC-5.

В Grafana провижинятся дашборды `LoanDebtors Notifications: Overview`,
`HTTP`, `Outbox`, `Delivery`, `Logs`, `Traces`,
`LoanDebtors Scheduler: Overview`, `LoanDebtors Audit Exporter: Overview`,
`LoanDebtors ABS: Overview` и `LoanDebtors Monitoring: Stack`. Они
объединены тегом `loandebtors`. Метрики и логи читаются из Prometheus и Loki,
TraceQL search в панелях дашборда не используется: Grafana 11.5 не
поддерживает backend-поиск трейсов. Отдельные трейсы открываются в Explore с
источником Tempo, а дашборд `Traces` показывает состояние конвейера трейсов
Collector и Tempo.

### 8.4.4 Структурированные логи

Логи одновременно пишутся в stdout в формате JSON и отправляются через
`LoggerProvider` в OTel Collector. JSON содержит `timestamp`, `level`,
`logger`, `message`, `service`, `service_version`, `environment`,
`correlation_id`, `trace_id`, `span_id`, `event`, HTTP-поля access-лога, а при
ошибке `exception_type` и `exception`. Поля `trace_id` и `span_id` позволяют
открыть трейс из строки лога.

Loki хранит логи 24 часа в томе `loki-data`. Индексными метками становятся
только `service.name`, `service.version` и `deployment.environment`, чтобы не
допустить высокой кардинальности. Остальные resource attributes, scope и log
attributes отбрасываются при приёме, а полный JSON остаётся телом записи и
разбирается в LogQL через `| json`.

Примеры запросов:

```logql
{service_name="notifications"} | json | level="ERROR"
```

```logql
{service_name="notifications"} | json | http_route="/v1/campaigns"
```

```logql
{service_name="audit_exporter"} | json | level="ERROR"
```

```logql
{service_name="email_channel"} | json | level="ERROR"
```

Access-лог пишется middleware с полями `http_method`, `http_route`,
`http_status_code` и `duration_ms`. Запросы `/health` в access-лог по
умолчанию не попадают, чтобы не засорять поток. Полные email и имена в логи не
пишутся; вспомогательная функция `mask_email` используется в тестах. Экспорт
логов отключается переменной `OTEL_LOGS_ENABLED=false`, при этом JSON в stdout
сохраняется.

### 8.4.5 Имена метрик и признаки работоспособности

Имена метрик и атрибутов объявляются константами в
`infrastructure/metrics.py`. Каждый сервис использует свой префикс:
`loandebtors.notifications`, `loandebtors.scheduler`, `loandebtors.audit_exporter`
и другие по имени сервиса. Collector и Prometheus преобразуют точки в
подчёркивания, поэтому в Prometheus метрика
`loandebtors.notifications.outbox.published` доступна как
`loandebtors_notifications_outbox_published_total`.

| Метрика                                                        | Тип       | Назначение                          |
|----------------------------------------------------------------|-----------|-------------------------------------|
| `loandebtors.notifications.outbox.published`                   | Counter   | Число опубликованных записей outbox |
| `loandebtors.notifications.outbox.failures`                    | Counter   | Число неудачных публикаций          |
| `loandebtors.notifications.outbox.errors`                      | Counter   | Ошибки чтения или обновления outbox |
| `loandebtors.notifications.outbox.batch.size`                  | Histogram | Размер обработанной пачки           |
| `loandebtors.notifications.outbox.processing.duration`         | Histogram | Длительность итерации relay         |
| `loandebtors.notifications.http.requests`                      | Counter   | Количество HTTP-запросов            |
| `loandebtors.notifications.http.duration`                      | Histogram | Длительность HTTP-запроса           |
| `loandebtors.notifications.consumer.messages`                  | Counter   | Обработанные сообщения consumers    |
| `loandebtors.notifications.consumer.failures`                  | Counter   | Ошибки обработки сообщений          |
| `loandebtors.notifications.consumer.retries`                   | Counter   | Возвраты сообщений в retry          |
| `loandebtors.notifications.consumer.dead_lettered`             | Counter   | Сообщения, отправленные в DLQ       |
| `loandebtors.notifications.consumer.duration`                  | Histogram | Длительность обработки сообщения    |
| `loandebtors.notifications.campaign.debtors`                   | Histogram | Размер выборки должников            |
| `loandebtors.notifications.campaign.messages`                  | Histogram | Число созданных сообщений           |
| `loandebtors.notifications.maintenance.requeued`               | Counter   | Повторно поставленные сообщения     |
| `loandebtors.notifications.maintenance.completed`              | Counter   | Завершенные кампании                |
| `loandebtors.notifications.maintenance.exhausted`              | Counter   | Сообщения с исчерпанным outbox       |
| `loandebtors.notifications.maintenance.deleted`                | Counter   | Удаленные записи retention          |

Audit Exporter использует метрики с префиксом `loandebtors.audit_exporter`:

| Метрика                                                         | Тип       | Назначение                              |
|-----------------------------------------------------------------|-----------|-----------------------------------------|
| `loandebtors.audit_exporter.audit.ingested`                     | Counter   | Число записанных audit-событий          |
| `loandebtors.audit_exporter.audit.ingest.failures`              | Counter   | Ошибки приёма audit-событий             |
| `loandebtors.audit_exporter.audit.conflicts`                    | Counter   | Конфликты event_id с другим содержимым  |
| `loandebtors.audit_exporter.audit.ingest.duration`              | Histogram | Длительность обработки сообщения        |
| `loandebtors.audit_exporter.audit.dlq.published`                | Counter   | Число сообщений, отправленных в DLQ     |
| `loandebtors.audit_exporter.audit.records.returned`             | Histogram | Размер выданной страницы журнала        |
| `loandebtors.audit_exporter.audit.query.duration`               | Histogram | Длительность чтения журнала             |
| `loandebtors.audit_exporter.queue.messages`                     | Gauge     | Глубина очередей audit.events           |
| `loandebtors.audit_exporter.consumer.running`                   | Gauge     | Признак запущенного консьюмера          |
| `loandebtors.audit_exporter.consumer.reconnects`                | Counter   | Переподключения консьюмера              |
| `loandebtors.audit_exporter.http.requests`                      | Counter   | Количество HTTP-запросов                |
| `loandebtors.audit_exporter.http.duration`                      | Histogram | Длительность HTTP-запроса               |

Email Channel использует префикс `loandebtors.email_channel`:

| Метрика                                                         | Тип       | Назначение                              |
|-----------------------------------------------------------------|-----------|-----------------------------------------|
| `loandebtors.email_channel.email.sent`                          | Counter   | Число отправленных писем                |
| `loandebtors.email_channel.email.failed`                        | Counter   | Число писем с ошибкой отправки          |
| `loandebtors.email_channel.email.duplicates`                    | Counter   | Повторно доставленные сообщения         |
| `loandebtors.email_channel.email.command.failures`              | Counter   | Ошибки обработки message.send           |
| `loandebtors.email_channel.email.send.duration`                 | Histogram | Длительность обработки message.send      |
| `loandebtors.email_channel.consumer.running`                    | Gauge     | Признак запущенного консьюмера          |
| `loandebtors.email_channel.consumer.reconnects`                 | Counter   | Переподключения консьюмера              |
| `loandebtors.email_channel.outbox.published`                    | Counter   | Опубликованные записи outbox            |
| `loandebtors.email_channel.outbox.failures`                     | Counter   | Ошибки публикации outbox                |
| `loandebtors.email_channel.outbox.errors`                       | Counter   | Ошибки чтения или обновления outbox     |
| `loandebtors.email_channel.outbox.batch.size`                   | Histogram | Размер обработанной пачки outbox        |
| `loandebtors.email_channel.outbox.processing.duration`          | Histogram | Длительность итерации outbox relay      |
| `loandebtors.email_channel.http.requests`                       | Counter   | Количество HTTP-запросов                |
| `loandebtors.email_channel.http.duration`                       | Histogram | Длительность HTTP-запроса               |

Заглушка АБС использует префикс `loandebtors.abs`:

| Метрика                                  | Тип       | Назначение                    |
|------------------------------------------|-----------|-------------------------------|
| `loandebtors.abs.http.requests`          | Counter   | Количество HTTP-запросов      |
| `loandebtors.abs.http.duration`          | Histogram | Длительность HTTP-запроса     |

Атрибут `service.name` ресурса коллектор преобразует в метку `job`. Остальные
ресурсные атрибуты, например `service.version` и `deployment.environment`,
доступны как постоянные метки метрик. Поэтому в Prometheus сервис выбирается
запросом `target_info{job="notifications"}`, а HTTP-метрики содержат метку
`service_name="notifications"`.

Служебные метрики Collector `otelcol_*` и Tempo `tempo_*` используются
дашбордом `LoanDebtors Monitoring: Stack` и не являются контрактом сервисов.
Они описывают состояние конвейера телеметрии, а не бизнес-операции.

### 8.4.6 Правила эксплуатации

- health сервиса не зависит от доступности OTel Collector, Loki и Мониторинга;
- телеметрия не содержит полных email, имён и других персональных данных;
  вспомогательная функция `mask_email` используется в тестах;
- `service.instance.id` не используется как метка метрик и не становится
  индексной меткой Loki;
- имена метрик и атрибутов совпадают с константами в коде;
- изменения состава провайдеров и бэкенда фиксируются в этом разделе и в
  конфигурации коллектора;
- отключение телеметрии выполняется переменной `OTEL_ENABLED=false` без
  изменения кода сервиса;
- отключение экспорта логов выполняется переменной `OTEL_LOGS_ENABLED=false`,
  JSON-логи в stdout при этом сохраняются;
- retention логов Loki ограничен 24 часами, объем ограничивается томом
  `loki-data`.
