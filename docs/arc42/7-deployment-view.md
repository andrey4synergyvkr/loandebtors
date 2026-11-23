# 7. Deployment View

Раздел описывает учебный стенд Docker Compose: узлы, контейнеры, порты и
размещение строительных блоков. Основание: разделы
[3-context-and-scope](3-context-and-scope.md),
[4-solution-strategy](4-solution-strategy.md) и
[5-building-block-view](5-building-block-view.md).

## 7.1 Infrastructure Level 1

Стенд запускается на одной машине разработчика или в CI. Реальные внешние
системы АБС и почтовый провайдер находятся вне стенда. Для автономного стенда
внешнюю АБС имитирует контейнер `abs`, который реализует контракт
`source/contracts/openapi/abs.yaml`. Заглушка не входит в границу системы и не
является строительным блоком. Все контейнеры работают в одной Docker-сети и
обращаются друг к другу по именам сервисов Compose. Общий файл стенда
`source/infra/compose.yaml` подключается корневым `compose.yaml`; запуск из корня
выполняется командой `docker compose up -d --build`.

| Узел / среда        | Описание                                                     | Размещаемые блоки                                              |
|---------------------|--------------------------------------------------------------|----------------------------------------------------------------|
| Локальный стенд     | Один экземпляр каждого контейнера, без Kubernetes и облака     | Все контейнеры раздела 7.2                                     |
| PostgreSQL          | Общая СУБД с отдельными схемами сервисов                      | Схемы `notification`, `scheduler`, `email_channel`, `audit`    |
| RabbitMQ            | Брокер сообщений с durable-очередями, retry-очередями и DLQ    | Exchange `loan-debtors.events` и очереди из AsyncAPI           |
| OTel Collector      | Единственная точка приёма телеметрии по OTLP                  | Приём трейсов, метрик и логов, экспорт в Tempo, Prometheus и Loki |
| Grafana Tempo       | Хранилище трейсов                                             | Трейсы всех сервисов                                           |
| Grafana Loki        | Хранилище логов                                               | Логи всех сервисов, retention 24 часа                          |
| Prometheus          | Хранилище метрик                                              | Метрики коллектора и сервисов                                  |
| Grafana             | UI Мониторинга                                                | Дашборды, Explore для метрик, трейсов и логов                  |
| Mailpit             | Локальный SMTP-сервер                                         | Приём писем Email Channel                                      |
| Сервисы             | Notifications, Scheduler, Email Channel, Audit Exporter        | REST API, consumers, outbox relay, миграции                    |
| Заглушка АБС        | Контейнер `abs` с JSON-фикстуром                               | Реализация контракта внешней АБС на стенде                     |

## 7.2 Infrastructure Level 2

| Элемент              | Порт              | Параметры и назначение                                                              |
|----------------------|-------------------|--------------------------------------------------------------------------------------|
| PostgreSQL           | 5432              | `postgres:16-alpine`, том `postgres-data`, healthcheck `pg_isready`                  |
| RabbitMQ             | 5672, 15672       | `rabbitmq:3.13-management-alpine`, веб-консоль на 15672, healthcheck `ping`          |
| Mailpit SMTP         | 1025              | Приём писем без внешней сети                                                        |
| Mailpit UI           | 8025              | Просмотр писем                                                                      |
| OTel Collector       | 4317, 4318, 8888, 8889 | OTLP gRPC, OTLP HTTP, внутренние метрики, Prometheus exporter                  |
| Grafana Tempo        | 3200              | OTLP-приём внутри сети, HTTP API и Grafana datasource                                |
| Grafana Loki         | 3100              | OTLP-приём логов, HTTP API и Grafana datasource                                     |
| Prometheus           | 9090              | Scrape коллектора `otel-collector:8889`                                             |
| Grafana              | 3000              | Provisioning datasource-ов и дашбордов, администратор из `.env`                      |
| Notifications        | 8001              | `/health`, `/v1/campaigns`, `/v1/campaigns/{id}/schedule`, `/start`, `/cancel`, `/v1/campaigns/{id}/messages`, `/v1/templates`, `/v1/templates/{key}`, `/versions/{version}` |
| Scheduler            | 8002              | `/health`                                                                           |
| Email Channel        | 8003              | `/health`, `/v1/config`, `/v1/config/validate`, `/v1/templates`, `/versions/{version}` |
| Audit Exporter       | 8004              | `/health`, `/v1/audit-records`, `/v1/audit-records/{event_id}`                      |
| ABS (заглушка)       | 9000              | `/health`, `/v1/debtors`, JSON-фикстур                                              |

### 7.2.1 Доступ к веб-интерфейсам

Учебные учётные данные задаются в `.env`. Grafana использует
`GRAFANA_ADMIN_USER` и `GRAFANA_ADMIN_PASSWORD`, по умолчанию `admin` / `admin`.
При первом входе Grafana может попросить сменить пароль. RabbitMQ Management
использует `RABBITMQ_DEFAULT_USER` и `RABBITMQ_DEFAULT_PASS`, по умолчанию
`loandebtors` / `loandebtors`. Prometheus, Tempo, Loki, Mailpit, OTel Collector
и Swagger-страницы сервисов в учебном стенде работают без аутентификации.
Tempo и Loki не имеют полноценного UI: трейсы и логи смотрят в Grafana
Explore.

Полный список адресов и команда сброса пароля Grafana приведены в
[README](../../README.md).

Тома:

| Том               | Назначение                              |
|-------------------|------------------------------------------|
| `postgres-data`   | Данные PostgreSQL                        |
| `prometheus-data` | Данные метрик Prometheus                 |
| `grafana-data`    | Настройки и состояние Grafana            |
| `tempo-data`      | Блоки и WAL трейсов Tempo                |
| `loki-data`       | Логи Loki                                |

Сервисы собираются общим образом
[Dockerfile](../../source/infra/docker/service.Dockerfile). При старте контейнер
применяет миграции Alembic, затем запускает uvicorn. Заглушка `abs` запускается
без миграций: в Compose для неё переопределена команда контейнера. Каждый сервис
хранит свою таблицу версий Alembic в схеме `public`, поэтому миграции
применяются независимо на общей СУБД. Healthcheck Compose проверяет `/health`
каждого сервиса. Notifications считается готовым только после успешного
подключения к PostgreSQL и RabbitMQ, первой итерации outbox relay, запуска
consumers `campaign.start` и `notification.results` и maintenance worker.
Scheduler считается готовым после подключения к PostgreSQL и RabbitMQ, запуска
consumer `scheduler.commands`, планировщика APScheduler и outbox relay.
Audit Exporter считается готовым после подключения к PostgreSQL и RabbitMQ и
запуска консьюмера `audit.events`. Email Channel считается готовым после
подключения к PostgreSQL и RabbitMQ, первой итерации outbox relay и запуска
консьюмера `email.commands`.

Телеметрия экспортируется по OTLP в Collector. Доступность Collector не
входит в health приложения: при его остановке сервисы продолжают работу.
Подробности провайдеров и метрик приведены в
[8-cross-cutting-concepts](8-cross-cutting-concepts.md), раздел 8.4.
