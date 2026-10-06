import abc
from collections.abc import Mapping
from typing import Any, ClassVar

from nld.exceptions import NotImplementedMethodException
from nld.flow.alerting.models import FlowAlert
from nld.utils.mixin import NldMixIn
from nld.utils.variable_utils import read_non_empty_env_var


class FlowAlertTransport(NldMixIn, abc.ABC):
    """One alerting technology: a way of delivering a ``FlowAlert``.

    Class attributes describe the transport so that readers — the project
    loader, ``nld scheduling info``, a scheduling generator — can reason
    about it without instantiating it:

    - ``name``: the key a project uses in ``alerting.transports``.
    - ``required_env_vars`` / ``optional_env_vars``: what the transport
      reads from the environment, secrets first (a webhook, a bot token),
      named after ``transport_env_var``.
    - ``settings_keys``: what it accepts under its own block of the
      declaration (``alerting.<name>``), for non-secret settings such as a
      channel name or a chat id.

    ``from_environment`` builds an instance from those two sources and
    returns None when the environment does not provide what the transport
    needs: an undeployed secret disables the transport, it never makes a
    run fail. ``send`` raises on failure; the service catches, logs and
    reports the alert as not delivered.
    """

    name: ClassVar[str] = ""
    optional_env_vars: ClassVar[tuple[str, ...]] = ()
    required_env_vars: ClassVar[tuple[str, ...]] = ()
    settings_keys: ClassVar[tuple[str, ...]] = ()

    def __init__(self) -> None:
        super().__init__()

    @classmethod
    def env_vars(cls) -> tuple[str, ...]:
        """Every environment variable the transport reads, required first."""
        return (*cls.required_env_vars, *cls.optional_env_vars)

    @classmethod
    def missing_env_vars(cls, environ: Mapping[str, str]) -> list[str]:
        """The required variables the environment does not provide."""
        return [
            name
            for name in cls.required_env_vars
            if read_non_empty_env_var(
                environ=environ,
                name=name,
            )
            is None
        ]

    @classmethod
    def validate_settings(cls, settings: Mapping[str, Any]) -> list[str]:
        """Return one message per settings key the transport does not accept."""
        unknown = sorted(set(settings) - set(cls.settings_keys))
        if not unknown:
            return []
        return [
            f"alert transport '{cls.name}' does not accept settings {unknown}; "
            f"accepted: {sorted(cls.settings_keys)}"
        ]

    @classmethod
    def reject_invalid_settings(cls, settings: Mapping[str, Any]) -> None:
        """Raise ``ValueError`` when the settings carry keys it does not accept."""
        errors = cls.validate_settings(settings=settings)
        if errors:
            raise ValueError("; ".join(errors))

    @classmethod
    @abc.abstractmethod
    def from_environment(
        cls,
        settings: Mapping[str, Any],
        environ: Mapping[str, str],
    ) -> "FlowAlertTransport | None":
        """Build the transport, None when the environment lacks what it needs."""
        raise NotImplementedMethodException(
            obj_class=cls,
            method_name="from_environment",
        )

    @abc.abstractmethod
    def send(self, alert: FlowAlert) -> None:
        """Deliver the alert, raising on failure."""
        raise NotImplementedMethodException(
            obj_class=type(self),
            method_name="send",
        )
