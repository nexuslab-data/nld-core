from typing import Any, ClassVar

from nld.governance.lookup import _owners_in_hierarchy
from nld.governance.ownership import FlowOwner, StructureOwner
from nld.parameters import ExecutionParameterDefinition
from nld.service.nld_entity_registry import EntityTypeNames
from nld.task.base import StandardTask


class OwnershipListTask(StandardTask):
    """List the ownership declarations visible from a namespace.

    Walks the namespace hierarchy (deepest first) and lists the resolved set of
    structure owners and flow owners — the nearest declaration of each wins.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(name="namespace", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.namespace = namespace
        self.execution_context.load_entities(
            entity_types=[
                EntityTypeNames.STRUCTURE_OWNER,
                EntityTypeNames.FLOW_OWNER,
            ],
            namespace=self.namespace,
        )

    def run(self, **kwargs: Any) -> bool:
        registry = self.execution_context.entity_registry

        self.log_info("Ownership declarations:")
        self.log_separator_line()

        rows: list[list[str]] = []
        rows.extend(
            self._collect_rows(
                registry=registry,
                entity_type=EntityTypeNames.STRUCTURE_OWNER,
                model_cls=StructureOwner,
                facet="data (structure)",
            )
        )
        rows.extend(
            self._collect_rows(
                registry=registry,
                entity_type=EntityTypeNames.FLOW_OWNER,
                model_cls=FlowOwner,
                facet="technical (flow)",
            )
        )

        if not rows:
            self.log_info("  No ownership declarations found")
            self.log_separator_line()
            return True

        rows.sort()
        self.log_aligned_table(
            headers=["Facet", "Namespace", "Name", "Team", "Contact", "Targets"],
            rows=rows,
        )
        self.log_info(f"({len(rows)} declaration(s))")
        self.log_separator_line()
        return True

    def _collect_rows(
        self,
        registry: Any,
        entity_type: str,
        model_cls: Any,
        facet: str,
    ) -> list[list[str]]:
        pairs = _owners_in_hierarchy(
            registry=registry,
            entity_type=entity_type,
            model_cls=model_cls,
            namespace=self.namespace,
        )
        return [
            [
                facet,
                str(source_namespace),
                owner.name,
                owner.team,
                owner.contact or "",
                ", ".join(owner.targets) if owner.targets else "(default)",
            ]
            for source_namespace, owner in pairs
        ]
