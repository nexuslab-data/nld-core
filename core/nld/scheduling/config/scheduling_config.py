from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from nld.pydantic import NamespaceMappingConfig, NldBaseModel
from nld.scheduling.models.trigger import SchedulingExecutionState

DEFAULT_ALERT_ON: list[SchedulingExecutionState] = ["FAILED"]
DEFAULT_MAX_ATTEMPTS = 1


class AlertingConfig(NldBaseModel):
    """Through which technologies, and on what, the flows of a namespace alert.

    ``transports`` names the technologies, by the name each transport class
    registers (``slack``, ``telegram``, or one a platform adds through
    ``flow.additional_alert_transports``). Each transport may take its own
    non-secret settings under a block of the same name — a Slack channel, a
    Telegram chat id — gathered into ``settings`` and validated against the
    keys the transport declares when the project loads; its secrets always
    come from the environment at run time. Any other key is rejected, so a
    typo surfaces as an error rather than as an ignored setting. An enabled
    declaration must name at least one transport: a reader must be able to
    tell exactly what a namespace alerts through.

    One declaration drives two alerting layers. nld itself alerts on what it
    observes while executing a flow — a violated data quality check, the
    flow's own error — through ``nld.flow.alerting``, with the runtime side
    (secrets, attempt budget) handed over by the scheduler in environment
    variables. The scheduler alerts on what nld could not report (a pod that
    never started, an out-of-memory kill) and reads ``alert_on`` from the
    labels the scheduling generator derives from this block. ``alert_on``
    filters both: a level a namespace does not list is raised by neither.

    ``enabled: false`` is the opt-out, and needs no transport. Alerting
    resolution walks past levels that declare nothing (see
    ``SchedulingNamespaceConfig.find_alerting_key``), so switching alerting
    off for a namespace has to be an explicit declaration rather than an
    empty one.

    Example YAML:
        alerting:
          transports: [slack, telegram]
          alert_on: [FAILED, WARNING]
          slack:
            channel: data-alerts
          telegram:
            chat_id: "-1001234567890"
    """

    model_config = ConfigDict(extra="forbid")

    alert_after_consecutive_failures: int = Field(default=1, ge=1)
    alert_on: list[SchedulingExecutionState] = Field(
        default_factory=lambda: list(DEFAULT_ALERT_ON),
        min_length=1,
    )
    enabled: bool = True
    settings: dict[str, dict[str, Any]] = Field(default_factory=dict)
    transports: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _gather_transport_blocks(cls, value: Any) -> Any:
        """Move each ``<transport>:`` block of the declaration into ``settings``.

        The YAML spells a transport's settings under the transport's own
        name, next to the typed keys; the model keeps them in one place.
        Only names listed in ``transports`` are gathered — anything else is
        left for the forbidden-extras check to reject.
        """
        if not isinstance(value, dict):
            return value
        declared = value.get("transports")
        if not isinstance(declared, list):
            return value
        names = [item.strip().lower() for item in declared if isinstance(item, str)]
        gathered = dict(value.get("settings") or {})
        remaining: dict[str, Any] = {}
        for key, item in value.items():
            if key in names:
                if not isinstance(item, dict):
                    raise ValueError(
                        f"alerting.{key} must be a mapping of settings, "
                        f"got {type(item).__name__}"
                    )
                gathered[key] = item
            else:
                remaining[key] = item
        remaining["settings"] = gathered
        return remaining

    @field_validator("alert_on", mode="before")
    @classmethod
    def _validate_alert_on(cls, value: Any) -> Any:
        """Normalise the declared states to upper case before validation."""
        if isinstance(value, list):
            return [item.upper() if isinstance(item, str) else item for item in value]
        return value

    @field_validator("transports", mode="before")
    @classmethod
    def _validate_transports(cls, value: Any) -> Any:
        """Normalise transport names to lower case, rejecting blanks and repeats."""
        if not isinstance(value, list):
            return value
        names: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("transports must be non-empty names")
            name = item.strip().lower()
            if name in names:
                raise ValueError(f"transport '{name}' is declared twice")
            names.append(name)
        return names

    @model_validator(mode="after")
    def _require_a_transport_when_enabled(self) -> "AlertingConfig":
        if self.enabled and not self.transports:
            raise ValueError(
                "an enabled alerting declaration must name at least one "
                "transport, e.g. transports: [slack]"
            )
        return self

    def settings_for(self, transport_name: str) -> dict[str, Any]:
        """The block a transport declared for itself, empty when none."""
        return dict(self.settings.get(transport_name) or {})


class SchedulingNamespaceMapping(NldBaseModel):
    """Scheduling defaults applying to every scheduled flow of a namespace.

    ``alerting`` is absent, not empty, when a level declares nothing about it:
    the two are told apart on purpose, see ``AlertingConfig``.
    """

    max_attempts: int = Field(default=DEFAULT_MAX_ATTEMPTS, ge=1, le=10)
    alerting: AlertingConfig | None = None


class SchedulingNamespaceConfig(NamespaceMappingConfig[SchedulingNamespaceMapping]):
    """Namespace-keyed scheduling settings, resolved to the nearest match.

    Keys are nld namespaces (``.`` for the root) and may carry a wildcard
    (``"*.extraction"``), resolved as ``NamespaceMappingConfig`` does: the
    most specific level wins, an exact key beats a wildcard at that level. That is
    what lets a whole layer share a policy (``"*.extraction"``) without
    repeating it for every sub-product.

    ``max_attempts`` and ``alerting`` resolve by different rules, which is the
    one surprise here: the retry budget takes the nearest mapping whatever it
    holds, while alerting keeps walking past mappings that declare none. See
    ``find_alerting_key`` for why.

    Example YAML:
        namespaces:
          .:
            scheduling:
              alerting:
                transports: [slack]
                alert_on: [FAILED, WARNING]
                slack:
                  channel: data-alerts
          "*.extraction":
            scheduling:
              max_attempts: 2
    """

    def get_max_attempts(self, namespace: str) -> int:
        """Return the namespace's retry budget, or the built-in default."""
        mapping = self.find_mapping(namespace=namespace)
        if mapping is None:
            return DEFAULT_MAX_ATTEMPTS
        return mapping.max_attempts

    def find_alerting_key(self, namespace: str) -> str | None:
        """Return the declared key whose alerting settings apply, or None.

        Unlike the retry budget, this walks past a mapping that declares no
        alerting instead of stopping there. Retry budgets and alert routing are
        naturally declared at different levels — a narrow ``"*.extraction"``
        raising only ``max_attempts`` sits under a broad ``.`` carrying the
        channel — and nearest-mapping-wins would otherwise let the narrow
        mapping silently switch alerting off for exactly the flows that retry
        the most. Switching it off is still possible, explicitly, with
        ``enabled: false``.
        """
        for key in self.find_matching_keys(namespace=namespace):
            if self.mappings[key].alerting is not None:
                return key
        return None

    def get_alerting(self, namespace: str) -> AlertingConfig | None:
        """Return the alerting declaration applying to a namespace, if any.

        A disabled declaration is returned as such rather than as None, so a
        reader can still tell "switched off here" from "never declared".
        """
        alerting_key = self.find_alerting_key(namespace=namespace)
        if alerting_key is None:
            return None
        return self.mappings[alerting_key].alerting
