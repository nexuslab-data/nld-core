from typing import Any

from nld.connector.base.events import (
    ConnectionOpeningError,
)
from nld.parameters import ExecutionParameterDefinition
from nld.task import BaseRunStatus, StandardTask
from nld.task.context import NldExecutionContext


class ConnectionDebugTask(StandardTask):
    """
    Debug a connection placed in a nld project
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

    def run(  # type: ignore[override]
        self,
        connection_name: str,
        profile_name: str | None = None,
        **kwargs: Any,
    ) -> bool:
        run_status = BaseRunStatus.SUCCESS.value

        try:
            data_connector = self.execution_context.get_data_connector(
                connection_name,
                profile_name=profile_name,
                open_connection=False,
            )
            data_connector.open_connection()
        except Exception as exc:
            self.log_event(ConnectionOpeningError(connection_name, exc=exc))

        return run_status
