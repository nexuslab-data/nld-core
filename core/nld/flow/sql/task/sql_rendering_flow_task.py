from typing import Any

from nld.flow.definition import DataFlowDefinition, NamespacedDataFlowDefinition
from nld.flow.sql.sql_query_resolver import render_sql_from_flow_definition
from nld.parameters import ExecutionParameterDefinition
from nld.pydantic import FLOWS_FOLDER_NAME
from nld.service.file_output_service import FileOutputService
from nld.task import BaseTask
from nld.task.context.context import NldExecutionContext


class SQLRenderingFlowTask(BaseTask):
    """Render a SQL SELECT query from flow metadata and write it to a file.

    Reads the flow definition's sql_rendering config or
    target_from_sources_mapping to determine the rendering strategy,
    resolves source structures from predecessors, and writes the
    resulting SQL to the output folder.
    """

    init_params = [
        ExecutionParameterDefinition(
            name="namespaced_data_flow_definition",
            mandatory=True,
        ),
        ExecutionParameterDefinition(
            name="source_predecessor_key",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="override_output_folder_path",
            mandatory=False,
        ),
    ]

    def __init__(
        self,
        namespaced_data_flow_definition: NamespacedDataFlowDefinition,
        source_predecessor_key: str | None = None,
        override_output_folder_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.namespaced_data_flow_definition = namespaced_data_flow_definition
        self.override_output_folder_path = override_output_folder_path
        self.source_predecessor_key = source_predecessor_key

    @property
    def data_flow_definition(self) -> DataFlowDefinition:
        """Return the unwrapped DataFlowDefinition."""
        return self.namespaced_data_flow_definition.model

    def run(self, **kwargs: Any) -> Any:
        """Render SQL from flow metadata and write to file."""
        flow_definition = self.data_flow_definition

        sql_content = render_sql_from_flow_definition(
            flow_definition=flow_definition,
            source_predecessor_key=self.source_predecessor_key,
        )

        file_name = f"{flow_definition.name}.sql"
        self._write_output_file(
            file_name=file_name,
            content=sql_content,
        )

        self.log_info(f"SQL rendered for flow '{flow_definition.name}'")

    def _write_output_file(
        self,
        file_name: str,
        content: str,
    ) -> None:
        """Write the rendered SQL to the output folder."""
        context = NldExecutionContext.require_current()
        namespace_str = str(self.namespaced_data_flow_definition.namespace)
        file_output_service = FileOutputService(
            root_folder_path=context.get_nld_root_folder_path(),
            override_output_folder_path=self.override_output_folder_path,
            entity_layout=context.entity_layout,
        )
        internal_folder_name = FLOWS_FOLDER_NAME
        file_output_service.write_file(
            file_name=file_name,
            content=content,
            internal_folder_name=internal_folder_name,
            namespace=namespace_str,
        )
        output_path = file_output_service.resolve_output_file_path(
            file_name=file_name,
            internal_folder_name=internal_folder_name,
            namespace=namespace_str,
        )
        self.log_info(f"SQL file written to {output_path}")
