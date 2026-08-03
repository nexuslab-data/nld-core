from sqlglot import select

from nld.flow.definition.field_lineage import FieldLineage
from nld.flow.sql.sql_rendering import resolve_template_field_expressions
from nld.flow.sql.transformation.base import SQLRenderingTransformation
from nld.structure import Structure


class SelectRendering(SQLRenderingTransformation):
    """Generate a simple SELECT with column aliases from a field mapping.

    Each entry in target_from_sources_mapping maps a target field name
    to a FieldLineage. The lineage can reference a source field
    (with optional expression wrapping) or provide a raw SQL expression.

    When a target_structure is provided, template fields with lineage
    rules that are not already in the explicit mapping are
    auto-included in the SELECT output.
    """

    @property
    def name(self) -> str:
        return "SELECT"

    def render(
        self,
        source_structures: dict[str, Structure],
        source_table_paths: dict[str, str],
        target_from_sources_mapping: dict[str, FieldLineage] | None = None,
        target_structure: Structure | None = None,
        dialect: str | None = None,
    ) -> str:
        auto_mapped = False
        if not target_from_sources_mapping:
            if target_structure is None:
                raise ValueError(
                    "target_from_sources_mapping or target_structure "
                    "is required for SelectRendering"
                )
            target_from_sources_mapping = self._auto_map_from_target_structure(
                target_structure=target_structure,
                source_structures=source_structures,
            )
            auto_mapped = True

        resolved_source_key: str | None = None
        already_mapped_fields: set[str] = set()
        select_expressions: list[str] = []

        for target_field, lineage in target_from_sources_mapping.items():
            already_mapped_fields.add(target_field)

            if not lineage.has_origin():
                select_expressions.append(
                    lineage.build_select_expression(
                        resolved_origin_field=None,
                        target_field=target_field,
                    ),
                )
                continue

            assert lineage.origin is not None
            predecessor_key, source_field = self._parse_source_reference(
                source_ref=lineage.origin,
                source_structures=source_structures,
            )

            if resolved_source_key is None:
                resolved_source_key = predecessor_key
            elif resolved_source_key != predecessor_key:
                raise ValueError(
                    f"SelectRendering only supports a single "
                    f"source table but mapping references multiple "
                    f"predecessors: '{resolved_source_key}' and "
                    f"'{predecessor_key}'"
                )

            select_expressions.append(
                lineage.build_select_expression(
                    resolved_origin_field=source_field,
                    target_field=target_field,
                ),
            )

        if target_structure is not None:
            template_expressions = resolve_template_field_expressions(
                target_structure=target_structure,
                source_structures=source_structures,
                already_mapped_fields=already_mapped_fields,
            )
            select_expressions.extend(template_expressions)

        if auto_mapped:
            null_expressions = self._build_null_expressions_for_unmapped_fields(
                target_structure=target_structure,
                already_mapped_fields=already_mapped_fields,
            )
            select_expressions.extend(null_expressions)

        if resolved_source_key is None:
            resolved_source_key = next(iter(source_table_paths))
        table_path = source_table_paths[resolved_source_key]

        query = select(*select_expressions).from_(table_path)
        return (
            query.sql(
                dialect=dialect,
                pretty=True,
            )
            + "\n"
        )

    def _auto_map_from_target_structure(
        self,
        target_structure: Structure,
        source_structures: dict[str, Structure],
    ) -> dict[str, FieldLineage]:
        """Auto-generate a target-to-source mapping based on field names.

        Iterates over the target structure fields and matches each one
        against the source structure fields by name. Only matched
        fields are included in the returned mapping. Unmatched fields
        are handled separately as NULL expressions.

        Fields directly based on a field template with a lineage are
        excluded so the lineage rule wins over the name-based match,
        matching the behavior of structure-template fields (which are
        never auto-mapped).

        Raises ValueError when no target field matches any source field.
        """
        all_source_fields: set[str] = set()
        for structure in source_structures.values():
            all_source_fields.update(structure.get_field_names())

        direct_lineage_fields = set(
            target_structure.get_direct_field_template_lineages().keys()
        )
        mapping: dict[str, FieldLineage] = {}
        for field_name in target_structure.get_field_names():
            if field_name in direct_lineage_fields:
                continue
            if field_name in all_source_fields:
                mapping[field_name] = FieldLineage(origin=field_name)

        if not mapping and not direct_lineage_fields:
            raise ValueError(
                "No target field could be auto-mapped to any source "
                "field. Target fields: "
                f"{target_structure.get_field_names()}, "
                f"source fields: {sorted(all_source_fields)}"
            )

        return mapping

    def _build_null_expressions_for_unmapped_fields(
        self,
        target_structure: Structure | None,
        already_mapped_fields: set[str],
    ) -> list[str]:
        """Build NULL AS expressions for target fields not yet mapped."""
        if target_structure is None:
            return []

        expressions: list[str] = []
        for field_name in target_structure.get_field_names():
            if field_name not in already_mapped_fields:
                expressions.append(f"NULL AS {field_name}")
                already_mapped_fields.add(field_name)
        return expressions

    def _parse_source_reference(
        self,
        source_ref: str,
        source_structures: dict[str, Structure],
    ) -> tuple[str, str]:
        """Parse a source reference into (predecessor_key, field_name).

        If source_ref contains a dot, split into
        predecessor_key.field_name. Otherwise iterate predecessors
        in declaration order, first containing the field wins.
        """
        if "." in source_ref:
            predecessor_key, field_name = source_ref.split(
                ".",
                maxsplit=1,
            )
            if predecessor_key not in source_structures:
                raise ValueError(
                    f"Predecessor key '{predecessor_key}' not found in "
                    f"source structures. "
                    f"Available: {list(source_structures.keys())}"
                )
            return predecessor_key, field_name

        for key, structure in source_structures.items():
            if source_ref in structure.get_field_names():
                return key, source_ref

        raise ValueError(
            f"Field '{source_ref}' not found in any source structure. "
            f"Searched: {list(source_structures.keys())}"
        )
