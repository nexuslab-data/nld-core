from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.scheduling.services import SchedulingResolver
from nld.scheduling.services.graph import SchedulingGraph, build_scheduling_node_id
from nld.service import EntityTypeNames, FileOutputService
from nld.task.base import StandardTask

DEPENDENCY_GRAPH_JSON_FILE_NAME = "scheduling_dependency_graph.json"
DEPENDENCY_GRAPH_MERMAID_FILE_NAME = "scheduling_dependency_graph.mmd"

ALLOWED_OUTPUT_FORMATS = ["json", "mermaid"]


class SchedulingDependencyGraphTask(StandardTask):
    """Build and output the scheduling dependency graph for one environment.

    Like the flow dependency graph, but scoped to a single environment: only
    tasks active in that environment are included, nodes are annotated with
    their trigger kind (and cron for schedule roots), and edges are trigger
    preconditions (explicit or derived).
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="downstream",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="environment",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="task_name",
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
            name="upstream",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        downstream: bool = False,
        environment: str | None = None,
        task_name: str | None = None,
        namespace: str | None = None,
        output_format: str = "json",
        override_output_folder_path: str | None = None,
        upstream: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        if (downstream or upstream) and not task_name:
            raise ValueError("--downstream and --upstream require --task-name.")

        self.downstream = downstream
        self.environment = environment
        self.task_name = task_name
        self.namespace = namespace
        self.output_format = output_format
        self.override_output_folder_path = override_output_folder_path
        self.upstream = upstream
        self.execution_context.load_entities(
            entity_types=[
                EntityTypeNames.DATA_FLOW_DEFINITION,
                EntityTypeNames.FLOW_TASK,
            ],
        )

    def run(self, **kwargs: Any) -> bool:
        """Resolve the scheduling graph for the environment and output it."""
        environment = self.execution_context.project.environments.resolve_name(
            requested=self.environment,
        )
        graph = SchedulingResolver(
            environment=environment,
            registry=self.execution_context.entity_registry,
        ).resolve()
        graph = self._apply_lineage_filter(graph=graph)

        file_output_service = FileOutputService(
            root_folder_path=self.execution_context.get_nld_root_folder_path(),
            override_output_folder_path=self.override_output_folder_path,
        )

        if self.output_format == "mermaid":
            file_name = DEPENDENCY_GRAPH_MERMAID_FILE_NAME
            file_output_service.write_file(
                file_name=file_name,
                content=graph.serialize_mermaid(),
            )
        else:
            file_name = DEPENDENCY_GRAPH_JSON_FILE_NAME
            file_output_service.write_json_file(
                file_name=file_name,
                data={
                    "environment": environment,
                    "nodes": graph.serialize_nodes(),
                    "edges": graph.serialize_edges(),
                },
            )

        self.log_info(
            f"Scheduling dependency graph for environment '{environment}' "
            f"written to {file_output_service.determine_output_folder_path()}"
            f"/{file_name}"
        )
        return True

    def _apply_lineage_filter(self, graph: SchedulingGraph) -> SchedulingGraph:
        """Restrict the graph to a task's lineage when --task-name is given."""
        if not self.task_name:
            return graph
        node_id = self._resolve_lineage_node_id(graph=graph)
        # Default (neither flag) shows the full lineage in both directions.
        upstream = self.upstream or not self.downstream
        downstream = self.downstream or not self.upstream
        return graph.get_lineage_subgraph(
            node_id=node_id,
            upstream=upstream,
            downstream=downstream,
        )

    def _resolve_lineage_node_id(self, graph: SchedulingGraph) -> str:
        """Resolve the scheduling node id from --task-name (and optional --namespace).

        When --namespace is omitted the task is located by name across the
        resolved graph; an ambiguous name requires --namespace to disambiguate.
        """
        if self.namespace:
            node_id = build_scheduling_node_id(
                namespace=self.namespace,
                task_name=self.task_name or "",
            )
            if not graph.has_node(node_id):
                raise ValueError(
                    f"Task '{node_id}' is not scheduled in the resolved environment."
                )
            return node_id

        matches = graph.find_node_ids_by_task_name(task_name=self.task_name or "")
        if not matches:
            raise ValueError(
                f"Task '{self.task_name}' is not scheduled in the resolved environment."
            )
        if len(matches) > 1:
            raise ValueError(
                f"Task '{self.task_name}' is scheduled in several namespaces "
                f"({', '.join(matches)}); pass --namespace to disambiguate."
            )
        return matches[0]
