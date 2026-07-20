from .structure_audit import StructureAudit


def _fmt(value: object) -> str:
    """Render a scalar for a markdown table cell (empty string for None)."""
    return "" if value is None else str(value)


def render_audit_to_markdown(audit: StructureAudit) -> str:
    """Render a StructureAudit as a standalone, human-readable markdown report.

    The output reproduces the data held in the audit YAML (target, metadata,
    per-column coverage and value distributions). It is a generated view, not
    the curated analysis markdown kept alongside the audit.
    """
    lines: list[str] = []
    target = audit.target
    metadata = audit.metadata

    lines.append(f"# {audit.name}")
    lines.append("")
    if audit.description:
        lines.append(audit.description)
        lines.append("")

    lines.append(f"**Structure**: `{audit.structure}`")
    lines.append(f"**Environment**: {target.environment}")
    location = ".".join(
        part for part in (target.database, target.schema_, target.table) if part
    )
    if location:
        lines.append(f"**Location**: `{location}`")
    if metadata.audited_at:
        lines.append(f"**Audited at**: {metadata.audited_at}")
    if metadata.row_count is not None:
        lines.append(f"**Rows**: {metadata.row_count}")

    sampling = metadata.sampling
    if sampling.sampled:
        details = ", ".join(
            part
            for part in (
                f"method={sampling.method}" if sampling.method else "",
                f"size={sampling.sample_size}"
                if sampling.sample_size is not None
                else "",
                f"fraction={sampling.fraction}"
                if sampling.fraction is not None
                else "",
            )
            if part
        )
        suffix = f" ({details})" if details else ""
        lines.append(f"**Sampling**: sampled{suffix}")
    else:
        lines.append("**Sampling**: full table")

    coverage = metadata.date_coverage
    if coverage is not None:
        on = (
            f" (on `{coverage.field_characterisation}`)"
            if coverage.field_characterisation
            else ""
        )
        lines.append(f"**Date coverage**: {coverage.from_} → {coverage.to}{on}")
    lines.append("")

    lines.append("## Field Coverage")
    lines.append("")
    lines.append(
        "| Column | Type | Nullable | PK | Non-null | Coverage | "
        "Distinct | Min | Max | Notes |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for column in audit.get_columns():
        cov = column.coverage
        pct = "" if cov.pct is None else f"{cov.pct}%"
        lines.append(
            f"| {column.name} | {_fmt(column.data_type)} "
            f"| {'yes' if column.nullable else 'no'} "
            f"| {'yes' if column.primary_key else ''} "
            f"| {_fmt(cov.non_null)} | {pct} | {_fmt(cov.distinct)} "
            f"| {_fmt(cov.min)} | {_fmt(cov.max)} | {_fmt(column.notes)} |"
        )
    lines.append("")

    columns_with_distribution = audit.get_columns_with_distribution()
    if columns_with_distribution:
        lines.append("## Distributions")
        lines.append("")
        for column in columns_with_distribution:
            distribution = column.distribution
            assert distribution is not None
            heading = column.name
            if distribution.truncated:
                heading = f"{heading} (top {distribution.top_n})"
            lines.append(f"### {heading}")
            lines.append("")
            lines.append("| Value | Count | % |")
            lines.append("|---|---|---|")
            for entry in distribution.values:
                pct = "" if entry.pct is None else f"{entry.pct}%"
                lines.append(f"| {_fmt(entry.value)} | {entry.count} | {pct} |")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
