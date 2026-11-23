# Исходный код

Монорепозиторий по разделу 4.4 архитектурной документации.

Общий запуск выполняется из корня репозитория через `compose.yaml`: он
подключает `source/infra/compose.yaml` и поднимает инфраструктуру вместе со
всеми сервисами.

```
source/
├── services/
│   ├── notifications/     # кампании, выборка должников, состояние сообщений
│   ├── scheduler/         # планирование запуска кампаний
│   ├── email_channel/     # рендеринг и отправка email
│   ├── audit_exporter/    # append-only журнал аудита
│   └── abs/               # заглушка внешней АБС для локального стенда
├── contracts/             # OpenAPI 3.1 и AsyncAPI 3.0
├── acceptance/            # сквозные E2E-тесты на Docker-стенде
└── infra/                 # Docker Compose, OTel collector, Dockerfile
```

Каждый сервис повторяет одну структуру:

```
<service>/
├── src/<package>/
│   ├── domain/            # сущности и правила, без внешних зависимостей
│   ├── application/       # сценарии использования
│   ├── ports/             # интерфейсы репозиториев, очереди, отправки
│   ├── adapters/          # HTTP, PostgreSQL, RabbitMQ, SMTP, АБС
│   └── infrastructure/    # логирование, телеметрия, конфигурация
├── migrations/            # Alembic, собственная схема сервиса
├── tests/
│   ├── unit/
│   ├── bdd/
│   └── integration/
├── Dockerfile-параметры   # общий source/infra/docker/service.Dockerfile
└── pyproject.toml
```

Правила:

- домен не импортирует FastAPI, SQLAlchemy, aio-pika и другие адаптеры;
- каждый сервис владеет своей схемой PostgreSQL, своими миграциями и своей
  таблицей версий Alembic;
- заглушка `abs` не является сервисом системы: у неё нет схемы PostgreSQL,
  миграций, RabbitMQ и outbox;
- прямые запросы в чужие схемы запрещены;
- обязательные комментарии (docstring) к публичным полям и методам, по-русски;
- приемочные тесты (Gherkin) пишутся по-русски;
- общий Docker Compose находится в корне репозитория и подключает
  `source/infra/compose.yaml`;
- зависимости собираются в composition root через Punq.

Документация: [docs/arc42](../docs/arc42/README.md).
