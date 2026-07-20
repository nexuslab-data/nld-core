import datetime
from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.service import EntityTypeNames
from nld.task.base import StandardTask
from nld.utils import (
    format_datetime_to_human_readable_string,
    parse_datetime_string,
)


class StructureAuditListTask(StandardTask):
    """List the structure audits visible from a namespace.

    Walks the entity registry (with the structure-audit search direction) and
    prints each audit with its namespace, audited structure, environment, the
    human-readable audit timestamp and column count, ordered by structure name
    then audit timestamp.
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
            entity_types=[EntityTypeNames.STRUCTURE_AUDIT]
        )

    def run(self, **kwargs: Any) -> bool:
        registry = self.execution_context.entity_registry
        keys = registry.get_structure_audit_keys(namespace=self.namespace)

        self.log_info("Structure Audits:")
        self.log_separator_line()
        if not keys:
            self.log_info("  No structure audits found")
            self.log_separator_line()
            return True

        rows: list[tuple[str, datetime.datetime, list[str]]] = []
        for key in keys:
            namespaced = registry.get_structure_audit(
                entity_key=key,
                namespace=self.namespace,
            )
            model = namespaced.model
            audited_at = model.metadata.audited_at
            audited_at_dt = (
                parse_datetime_string(value=audited_at) if audited_at else None
            )
            rows.append(
                (
                    str(model.structure),
                    audited_at_dt or datetime.datetime.min.replace(tzinfo=datetime.UTC),
                    [
                        key,
                        str(namespaced.namespace),
                        str(model.structure),
                        model.target.environment,
                        format_datetime_to_human_readable_string(dt=audited_at_dt)
                        if audited_at_dt
                        else "",
                        str(len(model.columns)),
                    ],
                )
            )

        rows.sort(key=lambda row: (row[0], row[1]))

        self.log_aligned_table(
            headers=[
                "Name",
                "Namespace",
                "Structure",
                "Environment",
                "Audited at",
                "Columns",
            ],
            rows=[row[2] for row in rows],
        )
        self.log_separator_line()
        return True
