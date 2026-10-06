from typing import Final

# A scheduler that runs ``nld flow execute`` (a Kestra pod, a CI job) hands
# the runtime side of alerting through these variables. The declarative side
# — which technologies a namespace alerts through, and on what — lives in
# ``nld_project.yml`` (``scheduling.alerting``) and never comes from the
# environment.

ALERTING_ENV_VAR_PREFIX: Final[str] = "NLD__ALERTING__"

# Attempt number (1-based) and budget the scheduler runs this execution with.
# A failure is only alerted on the last attempt: earlier ones are retried.
ATTEMPT_ENV_VAR: Final[str] = "NLD__ALERTING__ATTEMPT"
MAX_ATTEMPTS_ENV_VAR: Final[str] = "NLD__ALERTING__MAX_ATTEMPTS"

# The scheduler's own execution identifier, quoted in the alert so a reader
# can find the run in the scheduler's UI.
EXECUTION_REFERENCE_ENV_VAR: Final[str] = "NLD__ALERTING__EXECUTION_REFERENCE"

# The URL of that execution in the scheduler's UI, when the scheduler can
# build one: the alert then links the reference to the run instead of only
# quoting it. Only an http(s) URL is used.
EXECUTION_URL_ENV_VAR: Final[str] = "NLD__ALERTING__EXECUTION_URL"

# Template of the single line nld prints after the execution so the scheduler
# can read the outcome back (``string.Template`` syntax: ``$status``,
# ``$alerted``, ``$level``). Unset means nothing is printed.
OUTCOME_LINE_TEMPLATE_ENV_VAR: Final[str] = "NLD__ALERTING__OUTCOME_LINE_TEMPLATE"


def transport_env_var(
    transport_name: str,
    setting: str,
) -> str:
    """The environment variable carrying one setting of one transport.

    ``transport_env_var("slack", "webhook_url")`` is
    ``NLD__ALERTING__SLACK__WEBHOOK_URL``: the convention every built-in
    transport follows, and the one a scheduling generator relies on.
    """
    return f"{ALERTING_ENV_VAR_PREFIX}{transport_name.upper()}__{setting.upper()}"
