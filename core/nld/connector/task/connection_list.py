from typing import Any

from nld.connector.base.events import ConnectionListDisplayed
from nld.task import BaseRunStatus, StandardTask
from nld.task.context import NldExecutionContext


class ConnectionListTask(StandardTask):
    """
    List all available connections placed in a nld project
    """

    init_params = []
    run_params = []

    def __init__(
        self,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.execution_context = NldExecutionContext.require_current()

    def run(self, **kwargs: Any) -> bool:
        run_status = BaseRunStatus.SUCCESS.value

        connection_names = (
            self.execution_context.connection_configs.get_connection_names()
        )

        if not connection_names:
            self.log_info("No connections found in the project")
            return run_status

        connection_details = []
        for connection_name in sorted(connection_names):
            connection_config = (
                self.execution_context.connection_configs.get_connection_config(
                    connection_name=connection_name
                )
            )
            connection_details.append(
                {
                    "name": connection_name,
                    "type": connection_config.type,
                    "profiles": connection_config.get_available_profile_names(),
                }
            )

        self.log_event(ConnectionListDisplayed(connections=connection_details))

        return run_status
