# Интеграционные тесты Scheduler

Тесты запускают PostgreSQL и RabbitMQ через Testcontainers, применяют миграции
Scheduler и поднимают uvicorn на свободном порту. Проверяются полный health,
публикация `campaign.start` после срабатывания задания, audit-события и отмена
расписания. По умолчанию тесты исключены из прогона маркером `integration`.

```bash
uv run pytest -m integration source/services/scheduler/tests/integration -q
```

Если Docker недоступен, тест пропускается.
