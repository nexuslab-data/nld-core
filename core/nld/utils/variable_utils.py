import os

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
