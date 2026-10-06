from typing import Any, ClassVar

from nld.flow.definition import NamespacedDataFlowDefinition
from nld.parameters import ExecutionParameterDefinition
from nld.service import EntityTypeNames
from nld.task.base import StandardTask

from .sql_rendering_executor import SQLRenderingExecutor


class SQLRenderingExecutionTask(StandardTask):
    """Task responsible for executing the SQL rendering flow.

    This task loads a project, retrieves the data flow definitions from
    the entity registry by name or namespace, initializes a
    SQLRenderingExecutor for each flow, and executes the rendering.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="in_project",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="name",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="namespace",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        in_project: bool = False,
        name: str | None = None,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the SQLRenderingExecutionTask.

        Args:
            in_project: Write SQL directly into the project flows folder.
            name: Name of a single data flow to render.
            namespace: Namespace whose flows should all be rendered.
        """
        super().__init__(**kwargs)
        self.flow_name = name
        self.flow_namespace = namespace

        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.DATA_FLOW_DEFINITION]
        )

        if name is not None:
            namespaced_flow = (
                self.execution_context.entity_registry.get_data_flow_definition(
                    entity_key=name,
                    namespace=namespace,
                )
            )
            all_flows: dict[str, NamespacedDataFlowDefinition] = {
                name: namespaced_flow,
            }
        else:
            all_flows = (
                self.execution_context.entity_registry.get_data_flow_definition_dict(
                    namespace=namespace,
                )
            )

        self.flow_dict = self._filter_sql_flows(all_flows=all_flows)

        if not self.flow_dict:
            self.log_warn("No SQL flows found for the given parameters")

        self.override_output_folder_path = (
            self.execution_context.project.entities_root_folder_path
            if in_project
            else None
        )

    def _filter_sql_flows(
        self,
        all_flows: dict[str, NamespacedDataFlowDefinition],
    ) -> dict[str, NamespacedDataFlowDefinition]:
        """Keep only flows whose resolved task class is a SQLFlowTask."""
        from nld.flow.sql import SQLFlowTask

        project = self.execution_context.project
        sql_flows: dict[str, NamespacedDataFlowDefinition] = {}

        for flow_name, namespaced_flow in all_flows.items():
            try:
                _, task_class = namespaced_flow.model.resolve_task_module(
                    namespace=str(namespaced_flow.namespace),
                    entity_layout=project.entity_layout,
                    additional_task_paths=project.flows_python_additional_paths,
                    additional_flow_task_types=project.flow_config.additional_flow_task_types,
                )
            except (ValueError, ModuleNotFoundError):
                self.log_debug(
                    f"Skipping flow '{flow_name}': could not resolve task module"
                )
                continue

            if not issubclass(task_class, SQLFlowTask):
                self.log_debug(
                    f"Skipping flow '{flow_name}': "
                    f"task class '{task_class.__name__}' is not a SQLFlowTask"
                )
                continue

            sql_config = namespaced_flow.model.sql
            if sql_config is not None and sql_config.no_rendering:
                self.log_debug(f"Skipping flow '{flow_name}': no_rendering is enabled")
                continue

            sql_flows[flow_name] = namespaced_flow

        return sql_flows

    def run(self, **kwargs: Any) -> Any:
        """Execute the SQL rendering for all resolved flows."""
        failed_flows: list[tuple[str, str]] = []
        success_count = 0
        total = len(self.flow_dict)

        for flow_index, (flow_name, namespaced_flow) in enumerate(
            self.flow_dict.items(),
            start=1,
        ):
            self.log_info(f"Rendering flow {flow_index}/{total}: '{flow_name}'")
            try:
                executor = SQLRenderingExecutor(
                    namespaced_data_flow_definition=namespaced_flow,
                    override_output_folder_path=self.override_output_folder_path,
                )
                rendering_task = executor.init_task()
                executor.execute(task=rendering_task)
                success_count += 1
                self.log_info(f" ✅ Flow '{flow_name}' rendered successfully")
            except Exception as ex:
                self.log_error(f" ❌ Flow '{flow_name}' failed: {ex}")
                failed_flows.append((flow_name, str(ex)))

        summary = f"SQL rendering complete | ✅ {success_count}/{total} succeeded"
        if failed_flows:
            summary += f" | ❌ {len(failed_flows)}/{total} failed"
        self.log_info(summary)

        if failed_flows:
            for flow_name, error in failed_flows:
                self.log_warn(f"  - {flow_name}: {error}")
            raise RuntimeError(f"{len(failed_flows)} flow(s) failed to render")
