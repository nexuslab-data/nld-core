import sys
from typing import Any

from nld.connector.base.config_source import (
    DATA_CONNECTION_ENV_VAR_PREFIX,
)
from nld.connector.base.exceptions import (
    UnavailableConnectionConfigException,
)
from nld.parameters import ExecutionParameterDefinition
from nld.task import BaseRunStatus, StandardTask
from nld.task.context import NldExecutionContext


class ConnectionExportEnvironmentVariablesTask(StandardTask):
    """
    Export environment variables for a connection to the parent terminal.

    To load variables into your current shell, use eval:
        eval "$(nld connection export-env-var --connection-name <name>)"
    """

    init_params = []
    run_params = [
        "connection_name",
        ExecutionParameterDefinition(name="profile_name", mandatory=False),
    ]

    def __init__(
        self,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.execution_context = NldExecutionContext.require_current()

    def _build_export_statements(
        self,
        connection_name: str,
        profile_name: str | None,
    ) -> list[str]:
        """Build the list of export statements for the connection."""
        key_prefix = f"{DATA_CONNECTION_ENV_VAR_PREFIX}__{connection_name.upper()}"

        connection_config = (
            self.execution_context.connection_configs.get_connection_config(
                connection_name=connection_name
            )
        )

        params = connection_config.get_parameters_for_profile(profile_name=profile_name)

        statements = []

        type_env_var_name = f"{key_prefix}__TYPE".replace("-", "_")
        statements.append(f'export {type_env_var_name}="{connection_config.type}"')

        for key, value in sorted(params.items()):
            env_var_name = f"{key_prefix}__{key.upper()}".replace("-", "_")
            escaped_value = str(value).replace('"', '\\"')
            statements.append(f'export {env_var_name}="{escaped_value}"')

        return statements

    def run(  # type: ignore[override]
        self,
        connection_name: str,
        profile_name: str | None = None,
        **kwargs: Any,
    ) -> bool:
        run_status = BaseRunStatus.SUCCESS.value

        try:
            statements = self._build_export_statements(
                connection_name=connection_name,
                profile_name=profile_name,
            )

            is_interactive = sys.stdout.isatty()

            if is_interactive:
                print("\n# To load these variables into your current shell, run:")
                profile_arg = f" --profile-name {profile_name}" if profile_name else ""
                print(
                    f'# eval "$(nld connection export-env-var '
                    f'--connection-name {connection_name}{profile_arg})"'
                )
                print(f"\n# Connection: {connection_name}")
                if profile_name:
                    print(f"# Profile: {profile_name}")
                print("")

            for statement in statements:
                print(statement)

            if is_interactive:
                print("")

        except UnavailableConnectionConfigException:
            self.log_error(f"Connection '{connection_name}' not found")
            run_status = BaseRunStatus.FAIL.value
        except Exception as exc:
            self.log_error(f"Error exporting connection '{connection_name}': {exc}")
            run_status = BaseRunStatus.FAIL.value

        return run_status
