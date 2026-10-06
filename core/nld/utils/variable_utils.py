import os
from collections.abc import Mapping, Sequence
from typing import Protocol

from nld.exceptions import MissingEnvironmentVariableException

NLD_VAR_ENV_PREFIX = "NLD__VAR__"


def resolve_variables(
    project_variables: dict[str, str] | None = None,
) -> dict[str, str]:
    """Merge project-level variables with environment overrides.

    Environment variables prefixed with ``NLD__VAR__`` take precedence
    over project-level variables.  The prefix is stripped and the remaining
    key is lowercased to form the template variable name.

    Example:
        ``NLD__VAR__EXPO_ROLE=DEV_...`` → ``{{ expo_role }}``
    """
    variables: dict[str, str] = dict(project_variables or {})
    for env_key, env_value in os.environ.items():
        if env_key.startswith(NLD_VAR_ENV_PREFIX):
            var_name = env_key[len(NLD_VAR_ENV_PREFIX) :].lower()
            if var_name:
                variables[var_name] = env_value
    return variables


class EnvironmentVariableDeclaration(Protocol):
    """Structural type for a declared environment variable.

    Any object exposing ``name``, ``required`` and ``default`` attributes is
    accepted, so callers do not need to import a concrete model.
    """

    name: str
    required: bool
    default: str | None


def resolve_environment_variables(
    declarations: Sequence[EnvironmentVariableDeclaration] | None = None,
) -> dict[str, str]:
    """Resolve declared environment variables from the process environment.

    For each declaration the value is read from ``os.environ``. When the
    variable is absent its ``default`` is used; a required variable with no
    value and no default raises ``MissingEnvironmentVariableException``. An
    optional variable with neither a value nor a default is simply omitted
    from the result.
    """
    resolved: dict[str, str] = {}
    for declaration in declarations or []:
        value = os.environ.get(declaration.name, declaration.default)
        if value is None:
            if declaration.required:
                raise MissingEnvironmentVariableException(declaration.name)
            continue
        resolved[declaration.name] = value
    return resolved


def read_non_empty_env_var(
    environ: Mapping[str, str],
    name: str,
) -> str | None:
    """A non-empty, stripped environment value, or None when unset or blank.

    An unseeded secret reaches a process as an empty variable; readers that
    must treat it as absent go through this helper.
    """
    value = environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None
