import os
from collections.abc import Mapping

from nld.flow.alerting.env_var import (
    ATTEMPT_ENV_VAR,
    EXECUTION_REFERENCE_ENV_VAR,
    EXECUTION_URL_ENV_VAR,
    MAX_ATTEMPTS_ENV_VAR,
    OUTCOME_LINE_TEMPLATE_ENV_VAR,
)
from nld.pydantic import NldBaseModel
from nld.utils.variable_utils import read_non_empty_env_var


def _positive_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 1 else None


# Characters that would break the link markup of a transport (Slack's
# ``<url|text>``, an HTML ``href``); a scheduler UI URL never needs them.
_URL_FORBIDDEN_CHARACTERS = frozenset(' \t\n<>|"')


def _http_url(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.startswith(("http://", "https://")):
        return None
    if any(character in _URL_FORBIDDEN_CHARACTERS for character in value):
        return None
    return value


class FlowAlertingRuntimeSettings(NldBaseModel):
    """The transport-neutral runtime side of alerting, handed over by the scheduler.

    Everything is optional: run by hand with none of the variables set, nld
    neither reports nor retries anything, and the project's declaration only
    describes what its scheduled runs do. The transports' own secrets are
    read by the transports themselves (see ``nld.flow.alerting.transports``).
    """

    attempt: int | None = None
    execution_reference: str | None = None
    execution_url: str | None = None
    max_attempts: int | None = None
    outcome_line_template: str | None = None

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "FlowAlertingRuntimeSettings":
        """Read the settings from the process environment (or a stand-in)."""
        env = os.environ if environ is None else environ
        return cls(
            attempt=_positive_int(
                read_non_empty_env_var(
                    environ=env,
                    name=ATTEMPT_ENV_VAR,
                ),
            ),
            execution_reference=read_non_empty_env_var(
                environ=env,
                name=EXECUTION_REFERENCE_ENV_VAR,
            ),
            execution_url=_http_url(
                read_non_empty_env_var(
                    environ=env,
                    name=EXECUTION_URL_ENV_VAR,
                ),
            ),
            max_attempts=_positive_int(
                read_non_empty_env_var(
                    environ=env,
                    name=MAX_ATTEMPTS_ENV_VAR,
                ),
            ),
            outcome_line_template=read_non_empty_env_var(
                environ=env,
                name=OUTCOME_LINE_TEMPLATE_ENV_VAR,
            ),
        )

    @property
    def is_final_attempt(self) -> bool:
        """Whether a failure now would be final rather than retried.

        Without attempt information there is no retry to wait for, so the
        answer is yes.
        """
        if self.attempt is None or self.max_attempts is None:
            return True
        return self.attempt >= self.max_attempts
