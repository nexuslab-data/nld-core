import re

import sqlglot
from sqlglot import exp

from nld.flow.definition import DataFlowDefinition, FieldLineage
from nld.flow.structure_generation.exceptions import StructureGenerationException
from nld.pydantic import NldBaseModel
from nld.structure import Field, FieldDataType, Structure
from nld.utils import NldStrEnum


class ProjectionMode(NldStrEnum):
    """How the columns of a generated structure are derived from its source."""

    MAPPING = "mapping"
    PASSTHROUGH = "passthrough"
    SQL = "sql"


class ProjectedField(NldBaseModel):
    """One column of a generated structure and where it comes from.

    A field with ``source_field_name`` reuses the source field definition
    (description, characterisations, nested fields). A field with an
    ``expression`` and no source field is computed, so its type comes from
    ``data_type`` only.
    """

    data_type: str | None = None
    expression: str | None = None
    name: str
    source_field_name: str | None = None


class StructureProjection(NldBaseModel):
    """The ordered columns of a generated structure."""

    fields: list[ProjectedField]
    mode: ProjectionMode

    def get_field_names(self) -> list[str]:
        """Return the projected field names in their order."""
        return [projected_field.name for projected_field in self.fields]


def resolve_projection(
    flow_definition: DataFlowDefinition,
    predecessor_key: str,
    source_structure: Structure,
    sql_content: str | None,
    dialect: str | None,
) -> StructureProjection:
    """Resolve the projection of a flow onto its single source structure.

    The order mirrors how a SQL flow resolves its query at runtime: the
    ``.sql`` file wins, then ``target_from_sources_mapping``, and with
    neither every source field is passed through (the structure can then
    feed ``nld structure render``).

    Args:
        flow_definition: the flow whose target structure is generated.
        predecessor_key: key of the single predecessor in the flow.
        source_structure: the resolved predecessor structure.
        sql_content: content of the flow ``.sql`` file, None when absent.
        dialect: sqlglot dialect used to parse the SQL.

    Returns:
        The ordered projected fields.

    Raises:
        StructureGenerationException: when the projection is not supported or
            references a field missing from the source structure.
    """
    if sql_content is not None:
        return _resolve_sql_projection(
            sql_content=sql_content,
            source_structure=source_structure,
            dialect=dialect,
        )
    if flow_definition.target_from_sources_mapping:
        return _resolve_mapping_projection(
            mapping=flow_definition.target_from_sources_mapping,
            predecessor_key=predecessor_key,
            source_structure=source_structure,
        )
    return StructureProjection(
        fields=[
            ProjectedField(
                name=source_field.name,
                source_field_name=source_field.name,
            )
            for source_field in source_structure.get_all_fields()
        ],
        mode=ProjectionMode.PASSTHROUGH,
    )


def _resolve_mapping_projection(
    mapping: dict[str, FieldLineage],
    predecessor_key: str,
    source_structure: Structure,
) -> StructureProjection:
    """Build the projection from target_from_sources_mapping entries."""
    projected_fields: list[ProjectedField] = []
    for target_field_name, lineage in mapping.items():
        source_field_name = None
        if lineage.origin is not None:
            source_field_name = _resolve_mapping_origin(
                origin=lineage.origin,
                predecessor_key=predecessor_key,
                source_structure=source_structure,
                target_field_name=target_field_name,
            )
        projected_fields.append(
            ProjectedField(
                data_type=lineage.data_type,
                expression=lineage.expression,
                name=target_field_name,
                source_field_name=source_field_name,
            ),
        )
    return StructureProjection(
        fields=projected_fields,
        mode=ProjectionMode.MAPPING,
    )


def _resolve_mapping_origin(
    origin: str,
    predecessor_key: str,
    source_structure: Structure,
    target_field_name: str,
) -> str:
    """Resolve a mapping origin to a field name of the source structure."""
    field_name = origin
    if "." in origin:
        origin_predecessor_key, field_name = origin.split(
            ".",
            maxsplit=1,
        )
        if origin_predecessor_key != predecessor_key:
            raise StructureGenerationException(
                f"Mapping of field '{target_field_name}' references predecessor "
                f"'{origin_predecessor_key}', expected '{predecessor_key}'"
            )
    source_field = _find_source_field(
        source_structure=source_structure,
        field_name=field_name,
    )
    if source_field is None:
        raise StructureGenerationException(
            f"Mapping of field '{target_field_name}' references '{field_name}', "
            f"which is not a field of source structure '{source_structure.name}'"
        )
    return source_field.name


def _resolve_sql_projection(
    sql_content: str,
    source_structure: Structure,
    dialect: str | None,
) -> StructureProjection:
    """Build the projection from a single SELECT over the source structure.

    Supported shape: one ``SELECT`` reading one table (no join, no set
    operation), whose projections are columns, ``*``, aliased columns or
    aliased expressions. A ``CAST`` gives its target type to the field.
    """
    try:
        statements = [
            statement
            for statement in sqlglot.parse(
                sql_content,
                dialect=dialect,
            )
            if statement is not None
        ]
    except sqlglot.errors.ParseError as parse_error:
        raise StructureGenerationException(
            f"The flow SQL cannot be parsed: {parse_error}",
        ) from parse_error

    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise StructureGenerationException(
            "Only a flow SQL made of a single SELECT statement can be used "
            "to generate a structure"
        )
    select = statements[0]
    _check_single_source_table(
        select=select,
        source_structure=source_structure,
    )

    projected_fields: list[ProjectedField] = []
    for projection in select.expressions:
        projected_fields.extend(
            _project_sql_expression(
                projection=projection,
                source_structure=source_structure,
                dialect=dialect,
            ),
        )
    return StructureProjection(
        fields=projected_fields,
        mode=ProjectionMode.SQL,
    )


def _check_single_source_table(
    select: exp.Select,
    source_structure: Structure,
) -> None:
    """Ensure the SELECT reads only the source structure table."""
    from_clause = select.args.get("from_")
    if from_clause is None or select.args.get("joins"):
        raise StructureGenerationException(
            "The flow SQL must read exactly one table, without join"
        )
    source_table = from_clause.this
    if not isinstance(source_table, exp.Table):
        raise StructureGenerationException(
            "The flow SQL must read a table directly, not a subquery"
        )
    if source_table.name.lower() != source_structure.name.lower():
        raise StructureGenerationException(
            f"The flow SQL reads '{source_table.name}', expected the predecessor "
            f"structure '{source_structure.name}'"
        )


def _project_sql_expression(
    projection: exp.Expression,
    source_structure: Structure,
    dialect: str | None,
) -> list[ProjectedField]:
    """Turn one SELECT projection into one or several projected fields."""
    if isinstance(projection, exp.Star) or (
        isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)
    ):
        return [
            ProjectedField(
                name=source_field.name,
                source_field_name=source_field.name,
            )
            for source_field in source_structure.get_all_fields()
        ]

    if not projection.alias_or_name:
        raise StructureGenerationException(
            f"The SQL projection '{projection.sql(dialect=dialect)}' needs an alias"
        )
    target_name = _resolve_target_name(
        projection=projection,
        source_structure=source_structure,
    )
    expression = projection.this if isinstance(projection, exp.Alias) else projection

    data_type = None
    cast_expression = expression
    if isinstance(expression, exp.Cast):
        data_type = _normalize_cast_data_type(
            cast_data_type=expression.to.sql(dialect=dialect),
        )
        cast_expression = expression.this

    if isinstance(cast_expression, exp.Column):
        source_field = _find_source_field(
            source_structure=source_structure,
            field_name=cast_expression.name,
        )
        if source_field is None:
            raise StructureGenerationException(
                f"The flow SQL selects '{cast_expression.name}', which is not a "
                f"field of source structure '{source_structure.name}'"
            )
        return [
            ProjectedField(
                data_type=data_type,
                name=target_name,
                source_field_name=source_field.name,
            ),
        ]

    return [
        ProjectedField(
            data_type=data_type,
            expression=expression.sql(dialect=dialect),
            name=target_name,
        ),
    ]


def _resolve_target_name(
    projection: exp.Expression,
    source_structure: Structure,
) -> str:
    """Resolve the name of the field produced by a SELECT projection.

    Unquoted identifiers are case-insensitive in every supported engine, so
    an unquoted name takes the spelling of the source field it matches, and
    is lowercased otherwise. A quoted identifier keeps its exact case.

    Example:
        ``SELECT CD_CATEGORY`` over a ``cd_category`` source field produces
        ``cd_category``, while ``SELECT x AS "MixedCase"`` keeps ``MixedCase``.
    """
    name = projection.alias_or_name
    identifier: exp.Expression | None = None
    if isinstance(projection, exp.Alias):
        identifier = projection.args.get("alias")
    elif isinstance(projection, exp.Column):
        identifier = projection.this
    elif isinstance(projection, exp.Cast) and isinstance(projection.this, exp.Column):
        identifier = projection.this.this
    if isinstance(identifier, exp.Identifier) and identifier.quoted:
        return name

    source_field = _find_source_field(
        source_structure=source_structure,
        field_name=name,
    )
    if source_field is not None:
        return source_field.name
    return name.lower()


def _normalize_cast_data_type(cast_data_type: str) -> str:
    """Write a CAST target type in the compact form structures expect.

    Example:
        >>> _normalize_cast_data_type("decimal(10, 2)")
        'DECIMAL(10,2)'
    """
    return FieldDataType.from_string(
        re.sub(
            r"\s*,\s*",
            ",",
            cast_data_type.upper(),
        ),
    ).to_compact_string()


def _find_source_field(
    source_structure: Structure,
    field_name: str,
) -> Field | None:
    """Find a source field by name, falling back to a case-insensitive match."""
    all_fields = source_structure.get_all_fields()
    for source_field in all_fields:
        if source_field.name == field_name:
            return source_field
    for source_field in all_fields:
        if source_field.name.lower() == field_name.lower():
            return source_field
    return None
