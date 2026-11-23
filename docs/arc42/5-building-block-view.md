# 5. Строительные блоки

Раздел описывает статическую структуру LoanDebtors: строительные блоки, их
ответственности и важные интерфейсы. Основание: разделы
[1-introduction-and-goals](1-introduction-and-goals.md),
[2-constraints](2-constraints.md),
[3-context-and-scope](3-context-and-scope.md),
[4-solution-strategy](4-solution-strategy.md).

Внешние системы и акторы (АБС, почтовый провайдер, Мониторинг, оператор,
администратор, DevOps) описаны в разделе 3 и на диаграмме
[system-context.puml](../c4/system-context.puml).
В этом разделе они не являются строительными блоками системы.

Заглушка `abs` также не является строительным блоком. Это тестовый двойник
внешней АБС на локальном стенде, который реализует контракт
`source/contracts/openapi/abs.yaml` и описан в разделе 7.

## 5.1 Обзор системы

Система состоит из четырёх сервисов, общей СУБД и очереди RabbitMQ. Каждый сервис
является отдельной единицей развёртывания и владеет своей схемой БД.

### Декомпозиция системы на сервисы

| Строительный блок     | Ответственность                                                                                                                 | Требования                   |
|-----------------------|---------------------------------------------------------------------------------------------------------------------------------|------------------------------|
| `Notifications`       | Ядро системы: управление кампаниями и шаблонами, выборка должников, состояние сообщений, аудит-события, API оператора.          | F-01, F-02, F-04, F-05, QG-5 |
| `Scheduler`           | Планирование запуска кампаний по расписанию, хранение расписания, публикация заданий в очередь.                                 | F-02, F-04, QG-5             |
| `SMTP Adapter`        | Настройка канала, рендеринг email-шаблона, отправка писем через провайдера, ограничение скорости, публикация статусов доставки. | F-03, F-04, TC-3, TC-4       |
| `Audit Exporter`      | Приём audit-событий, append-only хранение журнала и read-only выгрузка для администратора.                                      | F-05, TC-7                   |
| `Storage`             | PostgreSQL: кампании, сообщения, расписание, настройки каналов и аудит в отдельных схемах.                                      | TC-7, QG-5                   |
| `Notifications Queue` | RabbitMQ: асинхронная передача сообщений, буферизация, повторные попытки и DLQ.                                                 | F-04, QG-5                   |

### Важные интерфейсы

| Интерфейс            | Тип                          | Описание                                                                                                                |
|----------------------|------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| Operator API         | HTTPS, REST, JSON, OpenAPI   | Управление кампаниями, шаблонами и запуском рассылки.                                                                   |
| Admin Channel API    | HTTPS, REST, JSON, OpenAPI   | Настройка конкретного адаптера канала, в первой версии SMTP.                                                            |
| Audit Export API     | HTTPS, REST, JSON, read-only | Выгрузка журнала аудита администратором.                                                                                |
| ABS Integration      | HTTPS, REST, JSON, pull      | Получение портфеля должников и контактных данных.                                                                       |
| Email Provider       | SMTP, MIME, STARTTLS         | Отправка писем через внешнего провайдера; на стенде используется Mailpit без TLS.                                       |
| Notifications Queue  | AMQP                         | Команды и события между сервисами.                                                                                      |
| Notification Command | JSON в AMQP                  | `message_id`, `campaign_id`, `debtor_id`, `channel`, `template_key`, `template_version`, переменные шаблона, получатель, `idempotency_key`. |
| Telemetry            | OTLP через gRPC или HTTP     | Метрики и трейсы в Мониторинг.                                                                                          |
| Storage              | SQL                          | Доступ к данным в пределах собственной схемы сервиса.                                                                   |
| Health               | HTTPS, JSON                  | Проверка работоспособности сервисов.                                                                                    |

## 5.2 Уровень 2

Каждый сервис использует Hexagonal Architecture и делится на слои `domain`,
`application`, `ports`, `adapters`, `infrastructure`. Домен не зависит от FastAPI,
SQLAlchemy и aio-pika. Сборка зависимостей выполняется через Punq в composition root.

Модули ниже являются логическими. Их физическое размещение по слоям и классам
описывается в коде и ADR.

Рендеринг сообщения выполняется в канальном сервисе, потому что формат зависит
от канала. `Notifications` передаёт канально-нейтральный `NotificationCommand`
с `template_key` и переменными, а `SMTP Adapter` превращает его в email-сообщение.

### 5.2.1 Whitebox Notifications

| Модуль                    | Ответственность                                                                                                           |
|---------------------------|---------------------------------------------------------------------------------------------------------------------------|
| `Campaign API`            | REST-эндпоинты оператора: создание, изменение, запуск и остановка кампаний.                                               |
| `Campaign Manager`        | Жизненный цикл кампании, шаблоны, выборка должников, проверка допустимости запуска.                                       |
| `Notification Composer`   | Выбирает логический шаблон, собирает переменные и формирует канально-нейтральный `NotificationCommand`.                   |
| `Debtor Selector`         | Адаптер АБС: постраничная выгрузка должников и контактов, проверка полноты выборки.                                       |
| `Message State`           | Состояния сообщений, идемпотентность по `idempotency_key`, повторные попытки, обработка статусов доставки.                 |
| `Audit Event Outbox`      | Запись audit-событий в outbox схемы notification.                                                                         |
| `Outbox Relay`            | Публикация событий из outbox в RabbitMQ с publisher confirms.                                                             |
| `Queue Gateway`           | Публикация `campaign.scheduled` и `message.send` с `template_key` и переменными, приём `message.sent` и `message.failed`. |
| `Notification Repository` | Доступ к схеме `notification`: кампании, логические шаблоны, снимки должников, сообщения, попытки, outbox.                |

Интерфейсы: Operator API, ABS Integration, Notifications Queue, Storage, Telemetry.

### 5.2.2 Whitebox Scheduler

| Модуль                | Ответственность                                                                          |
|-----------------------|------------------------------------------------------------------------------------------|
| `Schedule Manager`    | Приём `campaign.scheduled` и `campaign.cancelled`, регистрация, обновление и снятие заданий APScheduler. |
| `Schedule Trigger`    | APScheduler вызывает запуск задания в назначенное время.                                 |
| `Queue Publisher`     | Публикация `campaign.start` в очередь.                                                   |
| `Audit Event Outbox`  | Запись audit-событий планировщика в outbox схемы scheduler.                              |
| `Outbox Relay`        | Публикация событий из outbox в RabbitMQ.                                                 |
| `Schedule Repository` | Доступ к схеме `scheduler`: расписание, отметки отмены, состояние запусков, outbox.      |

Интерфейсы: Notifications Queue, Storage, Telemetry.

### 5.2.3 Whitebox SMTP Adapter

| Модуль               | Ответственность                                                                                             |
|----------------------|-------------------------------------------------------------------------------------------------------------|
| `Adapter Config API` | REST-эндпоинты администратора для настройки SMTP-адаптера.                                                  |
| `Message Consumer`   | Приём `message.send` с `template_key` и переменными из очереди.                                             |
| `Email Renderer`     | Рендеринг email-шаблона: тема, HTML, plain-text, подстановка переменных.                                    |
| `Rate Limiter`       | Глобальное ограничение скорости, целевое значение 10 писем в секунду.                                       |
| `SMTP Sender`        | Отправка MIME-сообщений через провайдера по SMTP; на стенде Mailpit без TLS, в production используется STARTTLS. |
| `Result Publisher`   | Публикация `message.sent` и `message.failed` с классификацией ошибок.                                       |
| `Audit Event Outbox` | Запись audit-событий отправки в outbox схемы email_channel.                                                 |
| `Outbox Relay`       | Публикация событий из outbox в RabbitMQ.                                                                    |
| `Channel Repository` | Доступ к схеме `email_channel`: email-варианты шаблонов, конфигурация адаптера, состояние отправок, outbox. |

Интерфейсы: Admin Channel API, Email Provider, Notifications Queue, Storage, Telemetry.

### 5.2.4 Whitebox Audit Exporter

| Модуль            | Ответственность                                                          |
|-------------------|--------------------------------------------------------------------------|
| `Audit Ingest`    | Приём `audit.event` из очереди, валидация и запись в append-only журнал. |
| `Audit Store`     | Хранение audit-событий в схеме `audit` без изменения и удаления записей. |
| `Audit Query API` | Read-only REST-эндпоинты выгрузки журнала для администратора.            |
| `Audit Reader`    | Постраничное чтение журнала и фильтрация по кампании, каналу, действию и времени. |

Интерфейсы: Notifications Queue, Audit Export API, Storage, Telemetry.

Запись в outbox синхронна и выполняется в транзакции сервиса. Журнал аудита
в схеме `audit` пишется асинхронно: `Audit Ingest` потребляет `audit.event`
и вызывает `Audit Store`.

### 5.2.5 Whitebox Storage

| Схема           | Владелец         | Содержимое                                                                           |
|-----------------|------------------|--------------------------------------------------------------------------------------|
| `notification`  | `Notifications`  | Кампании, логические шаблоны, снимки должников, сообщения, попытки отправки, outbox. |
| `scheduler`     | `Scheduler`      | Расписание кампаний, отметки отмены, состояние запусков, outbox.                     |
| `email_channel` | `SMTP Adapter`   | Email-варианты шаблонов, конфигурация SMTP-адаптера, состояние отправок, outbox.     |
| `audit`         | `Audit Exporter` | Append-only журнал аудита.                                                           |

Используется один физический инстанс PostgreSQL. Каждый сервис владеет своей
схемой и своими миграциями. Прямые запросы в чужие схемы запрещены. Обмен данными
между сервисами идёт через REST или RabbitMQ.

### 5.2.6 Whitebox Notifications Queue

| Элемент                | Ответственность                                                                 |
|------------------------|---------------------------------------------------------------------------------|
| `loan-debtors.events`  | Topic exchange для команд и событий.                                            |
| `scheduler.commands`   | Очередь событий `campaign.scheduled` и `campaign.cancelled` для планировщика.    |
| `notification.commands` | Очередь событий `campaign.start` для Notifications.                            |
| `email.commands`       | Очередь команд `message.send` с `template_key` и переменными для SMTP-адаптера. |
| `notification.results` | Очередь результатов `message.sent` и `message.failed`.                          |
| `audit.events`         | Очередь audit-событий для `Audit Exporter`.                                     |
| `*.retry`              | Retry-очереди с TTL. Экспоненциальный backoff применяется в outbox relay.       |
| `*.dlq`                | Dead-letter очереди для сообщений, которые не удалось обработать.               |

Используется один инстанс RabbitMQ. Очереди durable, публикация с publisher
confirms, потребление с manual ack и prefetch. Гарантия доставки at-least-once,
дедупликация по `message_id` в канале и по `idempotency_key` в Notifications.
Trace context передаётся в заголовках сообщений.

## 5.3 Уровень 3

Детализация уровня 3 в учебном проекте не выполняется. Модулей уровня 2 достаточно,
чтобы зафиксировать границы ответственности и интерфейсы. Конкретные классы,
доменные сущности и схемы таблиц описываются в коде, миграциях и ADR.
