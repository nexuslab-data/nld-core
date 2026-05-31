from typing import Any

from nld.flow.definition import NamespacedDataFlowDefinition
from nld.logging.logger import NldLoggable
from nld.task import BaseTask
from nld.task.context.context import NldExecutionContext

from .sql_rendering_flow_task import SQLRenderingFlowTask


class SQLRenderingExecutor(NldLoggable):
    """Executor for the SQL rendering task.

    Resolves the NamespacedDataFlowDefinition from the entity registry,
    builds the init parameters, and executes the SQLRenderingFlowTask.
    """

    def __init__(
        self,
        namespaced_data_flow_definition: NamespacedDataFlowDefinition,
        override_output_folder_path: str | None = None,
    ) -> None:
        super().__init__()
        self.namespaced_data_flow_definition = namespaced_data_flow_definition
        self.override_output_folder_path = override_output_folder_path

    def init_task(self) -> SQLRenderingFlowTask:
        """Initialize the SQL rendering flow task.

        Returns:
            An initialized SQLRenderingFlowTask instance.
        """
        init_params: dict[str, Any] = {
            "namespaced_data_flow_definition": self.namespaced_data_flow_definition,
        }

        if self.override_output_folder_path is not None:
            init_params["override_output_folder_path"] = (
                self.override_output_folder_path
            )

        nld_context = NldExecutionContext.require_current()
        cli_parameters = nld_context.task_request.get_parameters()
        init_params.update(
            {
                key: value
                for key, value in cli_parameters.items()
                if key in SQLRenderingFlowTask.get_init_params_keys()
            },
        )

        SQLRenderingFlowTask.check_init_params_dict(init_params)
        return SQLRenderingFlowTask(**init_params)

    def execute(
        self,
        task: BaseTask,
    ) -> Any:
        """Execute the SQL rendering task.

        Args:
            task: The initialized SQLRenderingFlowTask to execute.

        Returns:
            The result of the task execution.
        """
        return task.run()
