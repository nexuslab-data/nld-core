import os
from typing import Any, ClassVar

from nld.parameters import (
    ExecutionParameterDefinition,
)
from nld.service import EntityTypeNames
from nld.task.base import StandardTask


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

        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.DATA_FLOW_DEFINITION],
            namespace=namespace,
        )

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
            entity_layout=self.execution_context.project.entity_layout,
            additional_task_paths=self._additional_task_paths,
            additional_flow_task_types=self._additional_flow_task_types,
        )

    def run(self, **kwargs: Any) -> bool:
        """Display general information about the data flow definition."""
        self._display_flow_header()
        self._display_connectors_info()
        self._display_parameters_info()
        self._display_variables_info()
        self._display_entity_references()

        return True

    @property
    def _additional_task_paths(self) -> list[str]:
        return self.execution_context.project.flows_python_additional_paths

    @property
    def _additional_flow_task_types(self) -> dict[str, str]:
        return self.execution_context.project.flow_config.additional_flow_task_types

    def _display_flow_header(self) -> None:
        """Display data flow header information."""
        title_lines = [f"Data Flow: {self.data_flow_definition.name}"]
        if self.flow_namespace:
            title_lines.append(f"Namespace: {self.flow_namespace}")

        if self.data_flow_definition.task_type:
            task_display = f"{self.data_flow_definition.task_type} (task_type)"
        else:
            task_display = self.data_flow_definition.task or "(auto-resolved)"
        title_lines.append(f"Task: {task_display}")

        if self.data_flow_definition.write_strategy:
            title_lines.append(
                f"Write Strategy: {self.data_flow_definition.write_strategy}"
            )

        incremental_display = self._resolve_incremental_display()
        title_lines.append(f"Incremental: {incremental_display}")

        if self.data_flow_definition.target_structure:
            title_lines.append(
                f"Target Structure: {self.data_flow_definition.target_structure}"
            )

        task_class = self.data_flow_definition._require_task_class()
        title_lines.append(f"Task Class: {task_class.__name__}")

        self.log_section_header(*title_lines)
        self.log_empty_line()

    def _resolve_incremental_display(self) -> str:
        """Resolve the incremental type name shown in the info table."""
        return self.data_flow_definition.resolve_incremental_logic().definition.category

    def _display_connectors_info(self) -> None:
        """Display connectors information as an ASCII table."""
        self.log_info("Connectors:")
        self.log_separator_line()

        backend = self.data_flow_definition.state_backend_connector
        self.log_empty_line()
        if backend is None:
            self.log_info("  State Backend Connector: None")
        else:
            self.log_info(f"  State Backend Connector (primary)  : {backend.primary}")
            if backend.secondary is not None:
                self.log_info(
                    f"  State Backend Connector (secondary): {backend.secondary}"
                )
        self.log_empty_line()

        data_connectors = self.data_flow_definition.data_connectors or {}
        if data_connectors:
            self.log_info("  Data Connectors:")
            self.log_empty_line()
            self.log_aligned_table(
                headers=("Key", "Connection Name", "Profile"),
                rows=[
                    (
                        key,
                        connector_config.connector,
                        connector_config.profile_name or "(default)",
                    )
                    for key, connector_config in data_connectors.items()
                ],
            )
            self.log_empty_line()
        else:
            self.log_info("  No data connectors defined")
            self.log_empty_line()

        unique_connection_names = sorted(
            self.data_flow_definition.get_connector_connection_names()
        )
        self.log_info("  Unique Connection Names:")
        for connection_name in unique_connection_names:
            self.log_info(f"  - {connection_name}")
        self.log_empty_line()

        self.log_separator_line()
        self.log_empty_line()

    def _display_parameters_info(self) -> None:
        """Display parameters information as ASCII tables."""
        self.log_info("Parameters:")
        self.log_separator_line()

        if not self.data_flow_definition.params:
            self.log_info("  No parameters defined")
            self.log_separator_line()
            self.log_empty_line()
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
            self.log_empty_line()
            self.log_info("  Init Parameters:")
            self.log_empty_line()
            self._display_parameters_table(params=init_params)

        if incremental_params:
            self.log_empty_line()
            self.log_info("  Incremental Parameters:")
            self.log_empty_line()
            self._display_parameters_table(params=incremental_params)

        if run_params:
            self.log_empty_line()
            self.log_info("  Run Parameters:")
            self.log_empty_line()
            self._display_parameters_table(params=run_params)

        self.log_empty_line()
        self.log_separator_line()
        self.log_empty_line()

    def _display_variables_info(self) -> None:
        """Display the variables the flow expects.

        Secret values are never printed; only whether the variable is currently
        present in the environment (after the ``.nld/.env`` file is loaded).
        """
        self.log_info("Variables:")
        self.log_separator_line()

        variables = self.data_flow_definition.get_variables()
        if not variables:
            self.log_info("  No variables defined")
            self.log_separator_line()
            self.log_empty_line()
            return

        self.log_empty_line()
        self.log_aligned_table(
            headers=("Name", "Required", "Secret", "Default", "Present", "Description"),
            rows=[
                (
                    env_var.name,
                    str(env_var.required),
                    str(env_var.secret),
                    env_var.default if env_var.default is not None else "",
                    "yes" if os.environ.get(env_var.name) is not None else "no",
                    env_var.description,
                )
                for env_var in variables
            ],
        )
        self.log_empty_line()
        self.log_separator_line()
        self.log_empty_line()

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

        self.log_aligned_table(
            headers=headers,
            rows=rows,
        )

    def _display_entity_references(self) -> None:
        """Display entity references used by the flow."""
        self.log_info("Entity References:")
        self.log_separator_line()

        has_references = False

        if self.data_flow_definition.target_structure:
            self.log_empty_line()
            self.log_info(
                f"  Target Structure: {self.data_flow_definition.target_structure}"
            )
            has_references = True

        predecessors = self.data_flow_definition.predecessors
        if predecessors:
            self.log_empty_line()
            self.log_info("  Predecessors:")
            self.log_empty_line()
            self.log_aligned_table(
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

        self.log_empty_line()
        self.log_separator_line()
        self.log_empty_line()
