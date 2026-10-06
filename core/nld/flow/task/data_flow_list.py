from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.service import EntityTypeNames
from nld.task.base import StandardTask


class DataFlowListTask(StandardTask):
    """List the project's data flow definitions.

    ``--namespace`` scopes the listing the same way ``nld structure list``
    does; ``--incremental-type`` keeps only the flows using that incremental
    type, which is the filter worth having when reviewing a delta strategy
    across a product.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(name="namespace", mandatory=False),
        ExecutionParameterDefinition(name="incremental_type", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        namespace: str | None = None,
        incremental_type: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.namespace = namespace
        self.incremental_type = incremental_type
        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.DATA_FLOW_DEFINITION],
            namespace=self.namespace,
        )

    def run(self, **kwargs: Any) -> bool:
        """Display the matching data flow definitions as a table."""
        registry = self.execution_context.entity_registry
        flows = registry.get_data_flow_definition_dict(namespace=self.namespace)

        self.log_info("Data Flows:")
        self.log_separator_line()

        headers = ["Name", "Namespace", "Task Type", "Incremental", "Target Structure"]
        rows: list[list[str]] = []
        # Same-name flows from several namespaces are listed side by side,
        # so the plain name is shown next to its namespace column.
        for namespaced in sorted(
            flows.values(),
            key=lambda item: (item.model.name, str(item.namespace)),
        ):
            flow = namespaced.model
            incremental_type = self._incremental_type(flow=flow)
            if self.incremental_type and incremental_type != self.incremental_type:
                continue
            rows.append(
                [
                    flow.name,
                    str(namespaced.namespace),
                    flow.task_type or "",
                    incremental_type,
                    str(flow.target_structure or ""),
                ]
            )

        if not rows:
            self.log_info("  No data flows match")
            self.log_separator_line()
            return True

        self.log_aligned_table(
            headers=headers,
            rows=rows,
        )
        self.log_info(f"({len(rows)} data flow(s))")
        self.log_separator_line()
        return True

    @staticmethod
    def _incremental_type(flow: Any) -> str:
        """Return the flow's incremental type name, empty when it declares none."""
        if flow.incremental is None:
            return ""
        return str(flow.incremental.type)
