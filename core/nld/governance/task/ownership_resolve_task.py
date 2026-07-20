import json
import sys
from typing import Any, ClassVar

from nld.flow.graph.data_flow_graph import DataFlowGraph
from nld.governance.lookup import (
    ResolvedOwner,
    build_flow_graph,
    resolve_flow_owner,
    resolve_structure_data_owners,
    resolve_structure_technical_owners,
)
from nld.parameters import ExecutionParameterDefinition
from nld.pydantic import NldNamespace
from nld.service import EntityTypeNames
from nld.task import StandardTask
from nld.task.context import NldExecutionContext


def _join(namespace: str | None, name: str) -> str:
    """Build a full entity id from an optional namespace and a name."""
    if namespace is None or NldNamespace(namespace).is_root:
        return name
    return f"{namespace}.{name}"


def _format_owner(owner: ResolvedOwner) -> str:
    """One-line human rendering of a resolved owner."""
    origin = (
        owner.via if owner.via is not None else f"declared@{owner.source_namespace}"
    )
    contact = f" {owner.contact}" if owner.contact else ""
    return f"{owner.team}{contact} [{origin}]"


def _format_owners(owners: list[ResolvedOwner]) -> str:
    """Join resolved owners for a table cell, or a dash when there are none."""
    if not owners:
        return "-"
    return ", ".join(_format_owner(owner) for owner in owners)


class OwnershipResolveTask(StandardTask):
    """Resolve the effective owner(s) of a structure, a flow, or a namespace.

    For a structure, reports the pair ``{data_owner, technical_owner}``: the data
    owner(s) (nearest structure-owner declaration, else the union of upstream
    sources reached by lineage) and the technical owner(s) (the owner of its
    producing flow). For a flow, reports the technical owner. With only a
    ``--namespace`` (no ``--structure``/``--flow``), reports the pair for every
    structure under that namespace.

    Renders a human-friendly table by default; ``display_format="json"`` emits
    the full machine-readable payload to stdout instead.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(name="structure", mandatory=False),
        ExecutionParameterDefinition(name="flow", mandatory=False),
        ExecutionParameterDefinition(name="namespace", mandatory=False),
        ExecutionParameterDefinition(name="display_format", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        structure: str | None = None,
        flow: str | None = None,
        namespace: str | None = None,
        display_format: str = "text",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.execution_context = NldExecutionContext.require_current()
        self.structure = structure
        self.flow = flow
        self.namespace = namespace
        self.display_format = display_format

    def run(self, **kwargs: Any) -> bool:
        if self.structure is not None and self.flow is not None:
            raise ValueError("Provide at most one of --structure or --flow")
        if self.structure is None and self.flow is None and self.namespace is None:
            raise ValueError("Provide one of --structure, --flow or --namespace")

        self.execution_context.load_entities(
            entity_types=[
                EntityTypeNames.STRUCTURE,
                EntityTypeNames.DATA_FLOW_DEFINITION,
                EntityTypeNames.STRUCTURE_OWNER,
                EntityTypeNames.FLOW_OWNER,
            ],
        )
        registry = self.execution_context.entity_registry

        if self.flow is not None:
            flow_id = _join(self.namespace, self.flow)
            technical_owner = resolve_flow_owner(registry=registry, flow_id=flow_id)
            if self.display_format == "json":
                self._emit_json(
                    {
                        "flow": flow_id,
                        "technical_owner": (
                            technical_owner.model_dump() if technical_owner else None
                        ),
                    }
                )
            else:
                self._render_flow(flow_id, technical_owner)
            return True

        graph = build_flow_graph(registry=registry)
        if self.structure is not None:
            structure_ids = [_join(self.namespace, self.structure)]
        else:
            structure_dict = registry.get_structure_dict(namespace=self.namespace)
            structure_ids = sorted(wrapper.id for wrapper in structure_dict.values())

        resolved = [
            self._resolve_structure(registry, structure_id, graph)
            for structure_id in structure_ids
        ]

        if self.display_format == "json":
            if self.structure is not None:
                self._emit_json(resolved[0])
            else:
                self._emit_json(
                    {
                        "namespace": self.namespace or NldNamespace.ROOT_VALUE,
                        "structures": resolved,
                    }
                )
        else:
            self._render_structures(resolved)
        return True

    def _resolve_structure(
        self,
        registry: Any,
        structure_id: str,
        graph: DataFlowGraph,
    ) -> dict[str, Any]:
        data_owners: list[ResolvedOwner] = resolve_structure_data_owners(
            registry=registry,
            structure_id=structure_id,
            graph=graph,
        )
        technical_owners: list[ResolvedOwner] = resolve_structure_technical_owners(
            registry=registry,
            structure_id=structure_id,
            graph=graph,
        )
        return {
            "structure": structure_id,
            "data_owners": data_owners,
            "technical_owners": technical_owners,
        }

    def _emit_json(self, payload: dict[str, Any]) -> None:
        def _dump(value: Any) -> Any:
            if isinstance(value, ResolvedOwner):
                return value.model_dump()
            if isinstance(value, list):
                return [_dump(item) for item in value]
            if isinstance(value, dict):
                return {key: _dump(item) for key, item in value.items()}
            return value

        sys.stdout.write(
            json.dumps(_dump(payload), indent=2, ensure_ascii=False) + "\n"
        )
        sys.stdout.flush()

    def _render_flow(self, flow_id: str, owner: ResolvedOwner | None) -> None:
        self.log_info(f"Technical owner of flow {flow_id}:")
        self.log_separator_line()
        self.log_info(f"  {_format_owner(owner) if owner else '-'}")
        self.log_separator_line()

    def _render_structures(self, resolved: list[dict[str, Any]]) -> None:
        self.log_info("Ownership:")
        self.log_separator_line()
        if not resolved:
            self.log_info("  No structures found")
            self.log_separator_line()
            return
        rows = [
            [
                entry["structure"],
                _format_owners(entry["data_owners"]),
                _format_owners(entry["technical_owners"]),
            ]
            for entry in resolved
        ]
        self.log_aligned_table(
            headers=["Structure", "Data owner(s)", "Technical owner(s)"],
            rows=rows,
        )
        self.log_info(f"({len(rows)} structure(s))")
        self.log_separator_line()
