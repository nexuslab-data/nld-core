import abc

from nld.flow.definition.field_lineage import FieldLineage
from nld.structure import Structure
from nld.structure.field.field_template import FieldTemplateLineage


def resolve_template_field_expressions(
    target_structure: Structure,
    source_structures: dict[str, Structure],
    already_mapped_fields: set[str],
) -> list[str]:
    """Resolve template fields with lineage into SQL expressions.

    Iterates over all templates and their field templates. For each
    field template with a lineage that is not already in the explicit
    mapping, generates the appropriate SQL expression. When the target
    structure has a structure_type, lineage overrides for that type
    take precedence over the default rule.
    """
    target_type = target_structure.structure_type
    expressions: list[str] = []
    for template in target_structure.templates:
        for field_template in template.field_templates:
            lineage = field_template.lineage
            if lineage is None:
                continue
            field_name = field_template.field.name
            if field_name in already_mapped_fields:
                continue
            expression = resolve_lineage_expression(
                lineage=lineage,
                field_name=field_name,
                source_structures=source_structures,
                target_type=target_type,
            )
            expressions.append(expression)
            already_mapped_fields.add(field_name)
    return expressions


def resolve_lineage_expression(
    lineage: FieldTemplateLineage,
    field_name: str,
    source_structures: dict[str, Structure],
    target_type: str | None = None,
) -> str:
    """Build a SQL expression for a single lineage rule."""
    rule = lineage.resolve_for_target_type(target_type)
    if rule.expression is not None:
        return f"{rule.expression} AS {field_name}"

    assert rule.source_characterisation is not None
    source_field = find_source_field_by_characterisation(
        source_structures=source_structures,
        characterisation=rule.source_characterisation,
    )
    if source_field == field_name:
        return source_field
    return f"{source_field} AS {field_name}"


def find_source_field_by_characterisation(
    source_structures: dict[str, Structure],
    characterisation: str,
) -> str:
    """Find a source field by characterisation across all predecessors."""
    for structure in source_structures.values():
        field_name = structure.get_field_name_with_characterisation(
            characterisation,
        )
        if field_name is not None:
            return field_name
    raise ValueError(
        f"No field with characterisation '{characterisation}' found "
        f"in any source structure. "
        f"Searched: {list(source_structures.keys())}"
    )


class SQLRendering(abc.ABC):
    """Abstract base class for SQL rendering.

    A rendering transforms flow metadata (source structures,
    table paths, field mappings) into a SQL query string. Unlike
    generation strategies which work with a single source,
    renderings can reference multiple predecessor sources.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """The rendering name used for identification."""

    @abc.abstractmethod
    def render(
        self,
        source_structures: dict[str, Structure],
        source_table_paths: dict[str, str],
        target_from_sources_mapping: dict[str, FieldLineage] | None = None,
        target_structure: Structure | None = None,
        dialect: str | None = None,
    ) -> str:
        """Render flow metadata into a SQL SELECT query.

        Args:
            source_structures: mapping of predecessor key to resolved
                Structure entity.
            source_table_paths: mapping of predecessor key to fully
                qualified table path.
            target_from_sources_mapping: mapping of target field name to
                source field reference (predecessor_key.field_name or
                just field_name for auto-resolve).
            target_structure: optional target structure for resolving
                template fields with lineage rules.
            dialect: optional sqlglot dialect for rendering.

        Returns:
            The rendered SQL query as a string.
        """
