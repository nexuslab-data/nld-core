from collections.abc import Mapping
from typing import Any, ClassVar

import requests

from nld.flow.alerting.env_var import transport_env_var
from nld.flow.alerting.models import FlowAlert, FlowAlertLevel
from nld.flow.alerting.transports.base import FlowAlertTransport
from nld.utils.string_utils import escape_html_entities, truncate_text
from nld.utils.variable_utils import read_non_empty_env_var

# Slack caps a section's text at 3000 characters; keep well under it.
MAX_ITEMS = 20
MAX_SUMMARY_LENGTH = 1500

_LEVEL_EMOJIS: dict[str, str] = {
    FlowAlertLevel.WARNING: ":warning:",
    FlowAlertLevel.FAILED: ":rotating_light:",
}


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _execution_part(alert: FlowAlert) -> str | None:
    """The execution, linked to the scheduler's UI when its URL is known."""
    if alert.execution_url:
        label = escape_html_entities(alert.execution_reference or "open")
        return f"execution <{alert.execution_url}|{label}>"
    if alert.execution_reference:
        return f"execution `{alert.execution_reference}`"
    return None


def build_slack_payload(alert: FlowAlert) -> dict[str, Any]:
    """Build the JSON body of a Slack incoming-webhook post.

    ``text`` is the plain fallback (notifications, clients without blocks);
    ``blocks`` carry the same message with the details. The shape is the
    one the platform's scheduler-side alert flow posts too, so both kinds
    of alert read alike in the channel. Slack's mrkdwn reserves the same
    three characters as HTML, hence the shared escaping helper.
    """
    emoji = _LEVEL_EMOJIS[alert.level]
    environment = alert.environment or "-"
    headline = (
        f"{emoji} [{environment}] {alert.flow_path} finished in state "
        f"{alert.execution_status}"
    )
    summary = escape_html_entities(
        truncate_text(
            text=alert.summary,
            limit=MAX_SUMMARY_LENGTH,
        ),
    )
    blocks: list[dict[str, Any]] = [
        _section(f"{emoji} *{alert.level.value}* — `{alert.flow_path}`\n{summary}"),
    ]

    if alert.items:
        lines = [
            f"• *{escape_html_entities(item.label)}*: "
            f"{escape_html_entities(item.detail)}"
            for item in alert.items[:MAX_ITEMS]
        ]
        hidden = len(alert.items) - MAX_ITEMS
        if hidden > 0:
            lines.append(f"… and {hidden} more")
        blocks.append(
            _section(
                truncate_text(
                    text="\n".join(lines),
                    limit=MAX_SUMMARY_LENGTH * 2,
                ),
            ),
        )

    context_parts = [f"environment `{environment}`"]
    if alert.project_name:
        context_parts.append(f"project `{alert.project_name}`")
    context_parts.append(f"status `{alert.execution_status}`")
    execution_part = _execution_part(alert)
    if execution_part:
        context_parts.append(execution_part)
    context_parts.append(f"nld run `{alert.flow_uid}`")
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": " · ".join(context_parts)}],
        },
    )

    return {"text": headline, "blocks": blocks}


class SlackAlertTransport(FlowAlertTransport):
    """Slack, through an incoming webhook.

    An incoming webhook is bound to one channel when it is created, so the
    ``channel`` setting is informational: it tells a reader where the alerts
    go, it does not route them. Slack's incoming-webhook payload is also
    accepted by the Slack-compatible endpoints of Mattermost, Rocket.Chat
    and Discord.
    """

    name: ClassVar[str] = "slack"
    WEBHOOK_URL_ENV_VAR: ClassVar[str] = transport_env_var(
        transport_name="slack",
        setting="webhook_url",
    )
    required_env_vars: ClassVar[tuple[str, ...]] = (WEBHOOK_URL_ENV_VAR,)
    settings_keys: ClassVar[tuple[str, ...]] = ("channel",)

    DEFAULT_TIMEOUT_SECONDS = 10.0

    def __init__(
        self,
        webhook_url: str,
        channel: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__()
        self._timeout_seconds = timeout_seconds
        self._webhook_url = webhook_url
        self.channel = channel

    @classmethod
    def from_environment(
        cls,
        settings: Mapping[str, Any],
        environ: Mapping[str, str],
    ) -> "SlackAlertTransport | None":
        cls.reject_invalid_settings(settings=settings)
        webhook_url = read_non_empty_env_var(
            environ=environ,
            name=cls.WEBHOOK_URL_ENV_VAR,
        )
        if webhook_url is None:
            return None
        channel = settings.get("channel")
        return cls(
            webhook_url=webhook_url,
            channel=str(channel) if channel is not None else None,
        )

    def send(self, alert: FlowAlert) -> None:
        response = requests.post(
            self._webhook_url,
            json=build_slack_payload(alert=alert),
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
