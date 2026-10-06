from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.service import EntityTypeNames
from nld.task.base import StandardTask


class StructureAuditInfoTask(StandardTask):
    """Display a structure audit: target, metadata and per-column information.

    Prints the target environment and run metadata (sampling, date coverage,
    row count), the per-column listing with coverage, and the value
    distribution carried by each column that has one.
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
        super().__init__(**kwargs)
        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.STRUCTURE_AUDIT],
            namespace=namespace,
        )
        namespaced = self.execution_context.entity_registry.get_structure_audit(
            entity_key=name,
            namespace=namespace,
        )
        self.audit_namespace = namespaced.namespace
        self.model = namespaced.model

    def run(self, **kwargs: Any) -> bool:
        audit = self.model
        title_lines = [f"Structure Audit: {audit.name}"]
        if self.audit_namespace:
            title_lines.append(f"Namespace: {self.audit_namespace}")
        title_lines.append(f"Structure: {audit.structure}")
        if audit.description:
            title_lines.append(f"Description: {audit.description}")
        self.log_section_header(*title_lines)
        self.log_empty_line()

        self._render_target_and_metadata()
        self._render_columns()
        self._render_distributions()
        return True

    # rendering helpers below

    def _render_target_and_metadata(self) -> None:
        target = self.model.target
        metadata = self.model.metadata
        self.log_info("Target:")
        self.log_info(f"  environment   : {target.environment}")
        if target.connection:
            self.log_info(f"  connection    : {target.connection}")
        location = ".".join(
            part for part in (target.database, target.schema_, target.table) if part
        )
        if location:
            self.log_info(f"  location      : {location}")
        self.log_info("Metadata:")
        if metadata.audited_at:
            self.log_info(f"  audited_at    : {metadata.audited_at}")
        if metadata.row_count is not None:
            self.log_info(f"  row_count     : {metadata.row_count}")
        sampling = metadata.sampling
        if sampling.sampled:
            self.log_info(
                f"  sampling      : sampled "
                f"(method={sampling.method}, size={sampling.sample_size}, "
                f"fraction={sampling.fraction})"
            )
        else:
            self.log_info("  sampling      : full table")
        coverage = metadata.date_coverage
        if coverage is not None:
            self.log_info(
                f"  date_coverage : {coverage.from_} -> {coverage.to} "
                f"(on {coverage.field_characterisation})"
            )
        self.log_empty_line()

    def _render_columns(self) -> None:
        self.log_info("Columns:")
        if not self.model.columns:
            self.log_info("  No columns")
            self.log_empty_line()
            return
        rows: list[list[str]] = []
        for column in self.model.get_columns():
            coverage = column.coverage
            rows.append(
                [
                    column.name,
                    column.data_type or "",
                    "yes" if column.nullable else "no",
                    "yes" if column.primary_key else "",
                    "" if coverage.non_null is None else str(coverage.non_null),
                    "" if coverage.pct is None else f"{coverage.pct}%",
                    "" if coverage.distinct is None else str(coverage.distinct),
                    "" if coverage.min is None else str(coverage.min),
                    "" if coverage.max is None else str(coverage.max),
                ]
            )
        self.log_aligned_table(
            headers=[
                "Column",
                "Type",
                "Nullable",
                "PK",
                "Non-null",
                "Coverage",
                "Distinct",
                "Min",
                "Max",
            ],
            rows=rows,
        )
        self.log_empty_line()

    def _render_distributions(self) -> None:
        columns = self.model.get_columns_with_distribution()
        self.log_info("Distributions:")
        if not columns:
            self.log_info("  No distributions")
            return
        for column in columns:
            distribution = column.distribution
            assert distribution is not None
            suffix = " (truncated)" if distribution.truncated else ""
            self.log_info(
                f"  {column.name}: {len(distribution.values)} value(s), "
                f"top_n={distribution.top_n}{suffix}"
            )
            for entry in distribution.values:
                pct = "" if entry.pct is None else f" ({entry.pct}%)"
                self.log_info(f"      {entry.value}: {entry.count}{pct}")
