from typing import Any, ClassVar

from nld.flow.graph import (
    FLOW_NODE_TYPE,
    STRUCTURE_NODE_TYPE,
    DataFlowGraph,
    serialize_mermaid_graph,
    serialize_simplified_edges,
    serialize_simplified_nodes,
)
from nld.parameters import ExecutionParameterDefinition
from nld.service import FileOutputService
from nld.task.base import StandardTask

DEPENDENCY_GRAPH_JSON_FILE_NAME = "flow_dependency_graph.json"
DEPENDENCY_GRAPH_MERMAID_FILE_NAME = "flow_dependency_graph.mmd"

ALLOWED_OUTPUT_FORMATS = ["json", "mermaid"]


class DataFlowDependencyGraphTask(StandardTask):
    """
    Task that builds and outputs the flow dependency graph.

    Iterates all registered flow definitions, builds a bipartite
    graph of flow nodes and structure nodes with edges linking
    flows to their target and predecessor structures, and writes
    the result as a JSON or Mermaid file via FileOutputService.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="downstream",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="flow_name",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="namespace",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="output_format",
            mandatory=False,
            default_value="json",
            allowed_values=ALLOWED_OUTPUT_FORMATS,
        ),
        ExecutionParameterDefinition(
            name="override_output_folder_path",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="structure_name",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="upstream",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        downstream: bool = False,
        flow_name: str | None = None,
        namespace: str | None = None,
        output_format: str = "json",
        override_output_folder_path: str | None = None,
        structure_name: str | None = None,
        upstream: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        if flow_name and structure_name:
            raise ValueError("--flow-name and --structure-name are mutually exclusive.")

        if (
            (downstream or upstream)
            and not flow_name
            and not structure_name
            and not namespace
        ):
            raise ValueError(
                "--downstream and --upstream require"
                " --flow-name, --structure-name, or --namespace."
            )

        self.downstream = downstream
        self.flow_name = flow_name
        self.namespace = namespace
        self.output_format = output_format
        self.override_output_folder_path = override_output_folder_path
        self.structure_name = structure_name
        self.upstream = upstream
        self.execution_context.load_entities()

    def run(self, **kwargs: Any) -> bool:
        """Build the dependency graph and output it."""
        flow_dict = (
            self.execution_context.entity_registry.get_data_flow_definition_dict()
        )

        graph = DataFlowGraph(flow_dict=flow_dict)
        graph = self._apply_lineage_filter(graph=graph)

        file_output_service = FileOutputService(
            root_folder_path=self.execution_context.get_nld_root_folder_path(),
            override_output_folder_path=self.override_output_folder_path,
        )

        if self.output_format == "mermaid":
            file_name = DEPENDENCY_GRAPH_MERMAID_FILE_NAME
            content = serialize_mermaid_graph(graph=graph)
            file_output_service.write_file(
                file_name=file_name,
                content=content,
            )
        else:
            file_name = DEPENDENCY_GRAPH_JSON_FILE_NAME
            output = {
                "nodes": serialize_simplified_nodes(graph=graph),
                "edges": serialize_simplified_edges(graph=graph),
            }
            file_output_service.write_json_file(
                file_name=file_name,
                data=output,
            )

        self.log_info(
            f"Dependency graph written to "
            f"{file_output_service.determine_output_folder_path()}"
            f"/{file_name}"
        )

        return True

    def _apply_lineage_filter(
        self,
        graph: DataFlowGraph,
    ) -> DataFlowGraph:
        """Filter the graph to the lineage of the target node or namespace."""
        target_name = self.flow_name or self.structure_name
        node_type = (
            FLOW_NODE_TYPE
            if self.flow_name is not None
            else STRUCTURE_NODE_TYPE
            if self.structure_name is not None
            else None
        )

        include_downstream = self.downstream or not self.upstream
        include_upstream = self.upstream or not self.downstream

        return graph.get_scoped_subgraph(
            name=target_name,
            namespace=self.namespace,
            node_type=node_type,
            upstream=include_upstream,
            downstream=include_downstream,
        )
