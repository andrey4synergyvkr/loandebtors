"""Смоук-тесты контрактов портов и обмена Scheduler."""

from dataclasses import fields, is_dataclass

from scheduler.adapters.messaging.constants import QueueName, RoutingKey
from scheduler.ports import Clock, OutboxEntry, OutboxStore


def test_routing_keys_match_asyncapi_values() -> None:
    """Routing keys, используемые планировщиком, стабильны."""
    assert RoutingKey.CAMPAIGN_SCHEDULED.value == "campaign.scheduled"
    assert RoutingKey.CAMPAIGN_CANCELLED.value == "campaign.cancelled"
    assert RoutingKey.CAMPAIGN_START.value == "campaign.start"
    assert RoutingKey.AUDIT_EVENT.value == "audit.event"
    assert QueueName.SCHEDULER_COMMANDS.value == "scheduler.commands"
    assert QueueName.NOTIFICATION_COMMANDS.value == "notification.commands"


def test_outbox_entry_contains_transport_fields() -> None:
    """Запись outbox содержит все поля маршрутизации и повторов."""
    assert is_dataclass(OutboxEntry)
    names = {field.name for field in fields(OutboxEntry)}
    assert {
        "id",
        "event_type",
        "exchange",
        "routing_key",
        "payload",
        "headers",
        "occurred_at",
        "available_at",
        "attempts",
    } <= names


def test_ports_expose_expected_methods() -> None:
    """Порты объявляют методы, которые реализуют адаптеры."""
    assert hasattr(OutboxStore, "process_ready")
    assert hasattr(Clock, "now")
