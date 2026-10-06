from collections.abc import Mapping
from typing import Any, ClassVar

import requests

from nld.flow.alerting.env_var import transport_env_var
from nld.flow.alerting.models import FlowAlert, FlowAlertLevel
from nld.flow.alerting.transports.base import FlowAlertTransport
from nld.utils.string_utils import escape_html_entities, truncate_text
from nld.utils.variable_utils import read_non_empty_env_var

# Telegram rejects messages above 4096 characters.
MAX_ITEMS = 20
MAX_MESSAGE_LENGTH = 4000

_LEVEL_EMOJIS: dict[str, str] = {
    FlowAlertLevel.WARNING: "⚠️",
    FlowAlertLevel.FAILED: "\U0001f6a8",
}


def _execution_part(alert: FlowAlert) -> str | None:
    """The execution as HTML, linked to the scheduler's UI when its URL is known."""
    if alert.execution_url:
        label = escape_html_entities(alert.execution_reference or "open")
        href = escape_html_entities(alert.execution_url)
        return f'execution <a href="{href}">{label}</a>'
    if alert.execution_reference:
        return escape_html_entities(f"execution {alert.execution_reference}")
    return None


def build_telegram_text(alert: FlowAlert) -> str:
    """Build the HTML message body of a Telegram ``sendMessage`` call."""
    emoji = _LEVEL_EMOJIS[alert.level]
    environment = alert.environment or "-"
    lines = [
        f"{emoji} <b>{alert.level.value}</b> [{escape_html_entities(environment)}] "
        f"<code>{escape_html_entities(alert.flow_path)}</code>",
        escape_html_entities(alert.summary),
    ]
    if alert.items:
        lines.append("")
        lines.extend(
            f"• <b>{escape_html_entities(item.label)}</b>: "
            f"{escape_html_entities(item.detail)}"
            for item in alert.items[:MAX_ITEMS]
        )
        hidden = len(alert.items) - MAX_ITEMS
        if hidden > 0:
            lines.append(f"… and {hidden} more")
    context_parts = [escape_html_entities(f"status {alert.execution_status}")]
    if alert.project_name:
        context_parts.append(escape_html_entities(f"project {alert.project_name}"))
    execution_part = _execution_part(alert)
    if execution_part:
        context_parts.append(execution_part)
    context_parts.append(escape_html_entities(f"nld run {alert.flow_uid}"))
    lines.append("")
    lines.append(f"<i>{' · '.join(context_parts)}</i>")
    return truncate_text(
        text="\n".join(lines),
        limit=MAX_MESSAGE_LENGTH,
    )


class TelegramAlertTransport(FlowAlertTransport):
    """Telegram, through a bot.

    The bot token is a secret and comes from the environment; the chat the
    bot posts to is not, so it can be declared next to the alerting policy
    (``alerting.telegram.chat_id``) or handed over in the environment,
    which wins. Messages use Telegram's HTML parse mode.
    """

    name: ClassVar[str] = "telegram"
    BOT_TOKEN_ENV_VAR: ClassVar[str] = transport_env_var(
        transport_name="telegram",
        setting="bot_token",
    )
    CHAT_ID_ENV_VAR: ClassVar[str] = transport_env_var(
        transport_name="telegram",
        setting="chat_id",
    )
    optional_env_vars: ClassVar[tuple[str, ...]] = (CHAT_ID_ENV_VAR,)
    required_env_vars: ClassVar[tuple[str, ...]] = (BOT_TOKEN_ENV_VAR,)
    settings_keys: ClassVar[tuple[str, ...]] = ("chat_id",)

    API_BASE_URL: ClassVar[str] = "https://api.telegram.org"
    DEFAULT_TIMEOUT_SECONDS = 10.0

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        api_base_url: str | None = None,
    ) -> None:
        super().__init__()
        self._api_base_url = api_base_url or self.API_BASE_URL
        self._bot_token = bot_token
        self._timeout_seconds = timeout_seconds
        self.chat_id = chat_id

    @classmethod
    def from_environment(
        cls,
        settings: Mapping[str, Any],
        environ: Mapping[str, str],
    ) -> "TelegramAlertTransport | None":
        cls.reject_invalid_settings(settings=settings)
        bot_token = read_non_empty_env_var(
            environ=environ,
            name=cls.BOT_TOKEN_ENV_VAR,
        )
        if bot_token is None:
            return None
        chat_id = read_non_empty_env_var(
            environ=environ,
            name=cls.CHAT_ID_ENV_VAR,
        )
        if chat_id is None and settings.get("chat_id") is not None:
            chat_id = str(settings["chat_id"])
        if chat_id is None:
            raise ValueError(
                f"alert transport 'telegram' needs a chat id: declare "
                f"alerting.telegram.chat_id or set {cls.CHAT_ID_ENV_VAR}"
            )
        return cls(
            bot_token=bot_token,
            chat_id=chat_id,
        )

    @property
    def send_message_url(self) -> str:
        """The bot API endpoint the alert is posted to."""
        return f"{self._api_base_url}/bot{self._bot_token}/sendMessage"

    def send(self, alert: FlowAlert) -> None:
        response = requests.post(
            self.send_message_url,
            json={
                "chat_id": self.chat_id,
                "text": build_telegram_text(alert=alert),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
