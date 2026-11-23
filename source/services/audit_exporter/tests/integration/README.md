# Интеграционные тесты Audit Exporter

Тесты поднимают PostgreSQL 16 и RabbitMQ через Testcontainers, применяют
миграции, запускают uvicorn и проверяют полный сценарий: health, приём
`audit.event` из очереди, append-only журнал, фильтры и курсор, `audit.exported`
и DLQ.

```bash
uv run pytest -m integration source/services/audit_exporter/tests/integration -q
```

Нужны Docker и доступ к образам `postgres:16-alpine` и `rabbitmq:3.13-alpine`.
Если Docker недоступен, тесты пропускаются.
