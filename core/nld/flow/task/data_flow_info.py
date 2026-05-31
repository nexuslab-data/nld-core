from typing import Any, ClassVar

from nld.parameters import (
    ExecutionParameterDefinition,
)
from nld.task.base import StandardTask
from nld.utils.user_display import format_aligned_table


class DataFlowInfoTask(StandardTask):
    """
    Task responsible for displaying general information about an NLD data flow
    definition.

    This task loads a project, retrieves the data flow definition from the
    entity registry, and returns detailed information about the flow including
    task configuration, connectors, parameters, and entity references.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        "name",
        ExecutionParameterDefinition(name="namespace", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        name: str,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the DataFlowInfoTask.

        Args:
            name: Name of the data flow to display information about
            namespace: Optional namespace for the data flow
            **kwargs: Additional arguments (e.g., exec_uuid)
        """
        super().__init__(**kwargs)

        self.execution_context.load_entities()

        namespaced_data_flow_definition = (
            self.execution_context.entity_registry.get_data_flow_definition(
                entity_key=name,
                namespace=namespace,
            )
        )
        self.flow_namespace = namespaced_data_flow_definition.namespace
        self.data_flow_definition = namespaced_data_flow_definition.model

        # Load task module for later use
        self.data_flow_definition.load_task_module(
            namespace=self.flow_namespace,
            entity_path=self._entity_path,
            additional_task_paths=self._additional_task_paths,
            additional_flow_task_types=self._additional_flow_task_types,
        )

    def run(self, **kwargs: Any) -> bool:
        """Display general information about the data flow definition."""
        self._display_flow_header()
        self._display_connectors_info()
        self._display_parameters_info()
        self._display_entity_references()

        return True

    @property
    def _additional_task_paths(self) -> list[str]:
        return self.execution_context.project.flows_python_additional_paths

    @property
    def _additional_flow_task_types(self) -> dict[str, str]:
        return self.execution_context.project.flow_config.additional_flow_task_types

    @property
    def _entity_path(self) -> str:
        return self.execution_context.project.entity_path

    def _display_flow_header(self) -> None:
        """Display data flow header information."""
        self.log_info("=" * 60)
        self.log_info(f"Data Flow: {self.data_flow_definition.name}")
        if self.flow_namespace:
            self.log_info(f"Namespace: {self.flow_namespace}")

        if self.data_flow_definition.task_type:
            task_display = f"{self.data_flow_definition.task_type} (task_type)"
        else:
            task_display = self.data_flow_definition.task or "(auto-resolved)"
        self.log_info(f"Task: {task_display}")

        if self.data_flow_definition.write_strategy:
            self.log_info(f"Write Strategy: {self.data_flow_definition.write_strategy}")

        incremental_display = self._resolve_incremental_display()
        self.log_info(f"Incremental: {incremental_display}")

        if self.data_flow_definition.target_structure:
            self.log_info(
                f"Target Structure: {self.data_flow_definition.target_structure}"
            )

        task_class = self.data_flow_definition._require_task_class()
        self.log_info(f"Task Class: {task_class.__name__}")

        self.log_info("=" * 60)
        self.log_info("")

    def _resolve_incremental_display(self) -> str:
        """Resolve the incremental strategy name shown in the info table."""
        return self.data_flow_definition.resolve_incremental_logic().definition.category

    def _display_connectors_info(self) -> None:
        """Display connectors information as an ASCII table."""
        self.log_info("Connectors:")
        self.log_info("-" * 60)

        backend = self.data_flow_definition.state_backend_connector
        self.log_info("")
        if backend is None:
            self.log_info("  State Backend Connector: None")
        else:
            self.log_info(f"  State Backend Connector (primary)  : {backend.primary}")
            if backend.secondary is not None:
                self.log_info(
                    f"  State Backend Connector (secondary): {backend.secondary}"
                )
        self.log_info("")

        data_connectors = self.data_flow_definition.data_connectors or {}
        if data_connectors:
            self.log_info("  Data Connectors:")
            self.log_info("")
            self._display_ascii_table(
                headers=("Key", "Connection Name"),
                rows=[(key, connector) for key, connector in data_connectors.items()],
            )
            self.log_info("")
        else:
            self.log_info("  No data connectors defined")
            self.log_info("")

        unique_connection_names = sorted(
            self.data_flow_definition.get_connector_connection_names()
        )
        self.log_info("  Unique Connection Names:")
        for connection_name in unique_connection_names:
            self.log_info(f"  - {connection_name}")
        self.log_info("")

        self.log_info("-" * 60)
        self.log_info("")

    def _display_parameters_info(self) -> None:
        """Display parameters information as ASCII tables."""
        self.log_info("Parameters:")
        self.log_info("-" * 60)

        if not self.data_flow_definition.params:
            self.log_info("  No parameters defined")
            self.log_info("-" * 60)
            self.log_info("")
            return

        incremental_logic = self.data_flow_definition.resolve_incremental_logic()
        incremental_param_names = {
            param_def.name
            for param_def in incremental_logic.definition.param_definitions
        }

        init_params_keys = set(self.data_flow_definition.get_init_params_keys())
        run_params_keys = set(self.data_flow_definition.get_run_params_keys())

        init_params = []
        incremental_params = []
        run_params = []

        for param in self.data_flow_definition.params:
            if param.name in incremental_param_names:
                incremental_params.append(param)
            elif param.name in init_params_keys:
                init_params.append(param)
            elif param.name in run_params_keys:
                run_params.append(param)

        if init_params:
            self.log_info("")
            self.log_info("  Init Parameters:")
            self.log_info("")
            self._display_parameters_table(params=init_params)

        if incremental_params:
            self.log_info("")
            self.log_info("  Incremental Parameters:")
            self.log_info("")
            self._display_parameters_table(params=incremental_params)

        if run_params:
            self.log_info("")
            self.log_info("  Run Parameters:")
            self.log_info("")
            self._display_parameters_table(params=run_params)

        self.log_info("")
        self.log_info("-" * 60)
        self.log_info("")

    def _display_parameters_table(self, params: list[Any]) -> None:
        """Display a list of parameters as an ASCII table."""
        headers = ("Name", "Type", "Mandatory", "Default")
        rows: list[tuple[str, ...]] = []

        for param in params:
            param_dict = param.model_dump()
            default_value = param_dict.get("default_value", None)
            rows.append(
                (
                    param_dict.get("name", "Unknown"),
                    param_dict.get("data_type", "str"),
                    str(param_dict.get("mandatory", False)),
                    str(default_value) if default_value is not None else "",
                ),
            )

        self._display_ascii_table(
            headers=headers,
            rows=rows,
        )

    def _display_entity_references(self) -> None:
        """Display entity references used by the flow."""
        self.log_info("Entity References:")
        self.log_info("-" * 60)

        has_references = False

        if self.data_flow_definition.target_structure:
            self.log_info("")
            self.log_info(
                f"  Target Structure: {self.data_flow_definition.target_structure}"
            )
            has_references = True

        predecessors = self.data_flow_definition.predecessors
        if predecessors:
            self.log_info("")
            self.log_info("  Predecessors:")
            self.log_info("")
            self._display_ascii_table(
                headers=("Name", "Structure Reference", "Role", "Key Field"),
                rows=[
                    (
                        name,
                        str(predecessor.full_path),
                        predecessor.role or "",
                        predecessor.key_field or "",
                    )
                    for name, predecessor in predecessors.items()
                ],
            )
            has_references = True

        if not has_references:
            self.log_info("  No entity references defined")

        self.log_info("")
        self.log_info("-" * 60)
        self.log_info("")

    def _display_ascii_table(
        self,
        headers: tuple[str, ...],
        rows: list[tuple[str, ...]],
    ) -> None:
        """Display data as a formatted ASCII table with auto-width columns."""
        for line in format_aligned_table(headers=list(headers), rows=list(rows)):
            self.log_info(line)
