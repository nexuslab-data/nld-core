from nld.flow.alerting.registry import get_flow_alert_transport_registry

from .base import FlowAlertTransport
from .slack import SlackAlertTransport, build_slack_payload
from .telegram import TelegramAlertTransport, build_telegram_text

BUILTIN_FLOW_ALERT_TRANSPORT_CLASSES: list[type[FlowAlertTransport]] = [
    SlackAlertTransport,
    TelegramAlertTransport,
]


def _register_builtins() -> None:
    """Seed the registry with the built-in transports, once per process."""
    registry = get_flow_alert_transport_registry()
    for transport_class in BUILTIN_FLOW_ALERT_TRANSPORT_CLASSES:
        if not registry.has(name=transport_class.name):
            registry.register(transport_class=transport_class)


_register_builtins()

__all__ = [
    "BUILTIN_FLOW_ALERT_TRANSPORT_CLASSES",
    "FlowAlertTransport",
    "SlackAlertTransport",
    "TelegramAlertTransport",
    "build_slack_payload",
    "build_telegram_text",
]
