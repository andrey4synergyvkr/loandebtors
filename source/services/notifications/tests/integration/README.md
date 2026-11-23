# Интеграционные тесты

Здесь лежат тесты, которым нужен запущенный сервис или инфраструктура. Они
исключены из обычного прогона маркером `integration`.

Набор поднимает PostgreSQL и RabbitMQ через Testcontainers, применяет миграции
Alembic и проверяет:

- health с проверками `application`, `database`, `rabbitmq`, `outbox_relay`,
  `campaign_consumer`, `message_result_consumer` и `maintenance`;
- создание кампаний, шаблонов и расписаний;
- полный запуск кампании через `campaign.start`;
- повторную доставку сообщений из retry-очередей;
- повторную доставку `campaign.start` с routing key очереди.

Запуск:

```bash
uv run pytest -m integration source/services/notifications/tests/integration
```

Требуется работающий Docker. Если Docker недоступен, тест пропускается. В CI
переменная `INTEGRATION_REQUIRED=1` превращает такой пропуск в ошибку.
