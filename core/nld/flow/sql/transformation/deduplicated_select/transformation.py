from sqlglot import exp, select

from nld.flow.definition.field_lineage import FieldLineage
from nld.flow.sql.sql_rendering import find_source_field_by_characterisation
from nld.flow.sql.transformation.base import SQLRenderingTransformation
from nld.structure import (
    FieldCharacterisationDefinitionNames,
    Structure,
    StructureCharacterisationDefinitionNames,
)

CTE_ALIAS = "available_records"
ROW_NUMBER_ALIAS = "record_order_on_unique_key"


class DeduplicatedSelectTransformation(SQLRenderingTransformation):
    """Generate a deduplicated SELECT using ROW_NUMBER().

    Produces a CTE that partitions rows by the unique key and orders
    them by the last update timestamp descending, then selects only
    the first row per partition. Rows marked as deleted are excluded
    via a WHERE filter on the deletion flag field.
    """

    @property
    def name(self) -> str:
        return "DEDUPLICATED_SELECT"

    def render(
        self,
        source_structures: dict[str, Structure],
        source_table_paths: dict[str, str],
        target_from_sources_mapping: dict[str, FieldLineage] | None = None,
        target_structure: Structure | None = None,
        dialect: str | None = None,
    ) -> str:
        source_structure = next(iter(source_structures.values()))
        source_table_path = self._resolve_source_table_path(source_structure)

        unique_key_field_names = self._resolve_unique_key_field_names(
            source_structure,
        )
        last_update_field = source_structure.get_last_update_tst_field(
            none_throws_exception=True,
        )
        assert last_update_field is not None
        last_update_field_name = last_update_field.name
        deletion_flag_field_name = (
            source_structure.get_field_name_with_characterisation(
                FieldCharacterisationDefinitionNames.REC_DELETION_FLAG,
                none_throws_exception=True,
            )
        )
        assert deletion_flag_field_name is not None

        field_names = self._resolve_select_field_names(
            source_structure=source_structure,
            target_structure=target_structure,
        )

        cte_extra_fields, outer_template_expressions = (
            self._resolve_template_field_lineage(
                target_structure=target_structure,
                source_structures=source_structures,
                already_mapped_fields=set(field_names),
            )
        )

        cte_field_names = list(field_names) + cte_extra_fields

        cte_query = self._build_cte_select(
            field_names=cte_field_names,
            source_table_path=source_table_path,
            partition_fields=unique_key_field_names,
            order_field=last_update_field_name,
            deletion_flag_field=deletion_flag_field_name,
        )

        null_expressions = self._build_null_expressions_for_unmapped_fields(
            source_field_names=field_names,
            target_structure=target_structure,
        )

        outer_query = self._build_outer_select(
            field_names=field_names,
            null_expressions=null_expressions,
            template_expressions=outer_template_expressions,
        )
        full_query = outer_query.with_(
            CTE_ALIAS,
            as_=cte_query,
        )

        return (
            full_query.sql(
                dialect=dialect,
                pretty=True,
            )
            + "\n"
        )

    def _resolve_source_table_path(
        self,
        source_structure: Structure,
    ) -> str:
        """Build the source table path from structure properties."""
        schema = source_structure.get_property("schema")
        table = source_structure.get_property("table")
        if table is None:
            table = source_structure.name

        if schema is not None:
            return f"{schema}.{table}"
        return table

    def _resolve_select_field_names(
        self,
        source_structure: Structure,
        target_structure: Structure | None,
    ) -> list[str]:
        """Resolve field names for the SELECT clause.

        When a target_structure is provided, auto-maps target fields
        by matching names against source fields. Fields with explicit
        lineage in templates are excluded so they are handled by
        _resolve_template_field_lineage instead.
        """
        if target_structure is None:
            return source_structure.get_field_names()

        lineage_fields = self._get_template_lineage_field_names(
            target_structure=target_structure,
        )
        source_field_names = set(source_structure.get_field_names())
        mapped_fields = [
            field_name
            for field_name in target_structure.get_field_names()
            if field_name in source_field_names and field_name not in lineage_fields
        ]

        if not mapped_fields:
            raise ValueError(
                "No target field could be auto-mapped to any source "
                "field. Target fields: "
                f"{target_structure.get_field_names()}, "
                f"source fields: {sorted(source_field_names)}"
            )

        return mapped_fields

    @staticmethod
    def _get_template_lineage_field_names(
        target_structure: Structure,
    ) -> set[str]:
        """Collect target field names that have explicit lineage in templates."""
        lineage_fields: set[str] = set()
        for template in target_structure.templates:
            for field_template in template.field_templates:
                if field_template.lineage is not None:
                    lineage_fields.add(field_template.field.name)
        return lineage_fields

    def _build_null_expressions_for_unmapped_fields(
        self,
        source_field_names: list[str],
        target_structure: Structure | None,
    ) -> list[str]:
        """Build NULL AS expressions for target fields not in source."""
        if target_structure is None:
            return []

        mapped_set = set(source_field_names)
        return [
            f"NULL AS {field_name}"
            for field_name in target_structure.get_field_names()
            if field_name not in mapped_set
        ]

    def _build_cte_select(
        self,
        field_names: list[str],
        source_table_path: str,
        partition_fields: list[str],
        order_field: str,
        deletion_flag_field: str,
    ) -> exp.Select:
        """Build the CTE inner SELECT with ROW_NUMBER window."""
        row_number_expr = exp.Window(
            this=exp.RowNumber(),
            partition_by=[exp.column(field) for field in partition_fields],
            order=exp.Order(
                expressions=[
                    exp.Ordered(
                        this=exp.column(order_field),
                        desc=True,
                    ),
                ],
            ),
        )

        return (
            select(
                *field_names,
                row_number_expr.as_(ROW_NUMBER_ALIAS),
            )
            .from_(source_table_path)
            .where(f"{deletion_flag_field} = 0")
        )

    def _build_outer_select(
        self,
        field_names: list[str],
        null_expressions: list[str] | None = None,
        template_expressions: list[str] | None = None,
    ) -> exp.Select:
        """Build the outer SELECT filtering on the row number."""
        all_expressions: list[str] = list(field_names)
        if null_expressions:
            all_expressions.extend(null_expressions)
        if template_expressions:
            all_expressions.extend(template_expressions)
        return (
            select(*all_expressions).from_(CTE_ALIAS).where(f"{ROW_NUMBER_ALIAS} = 1")
        )

    def _resolve_template_field_lineage(
        self,
        target_structure: Structure | None,
        source_structures: dict[str, Structure],
        already_mapped_fields: set[str],
    ) -> tuple[list[str], list[str]]:
        """Resolve template fields with lineage for CTE and outer SELECT.

        Source characterisation lineage fields are added to the CTE so
        they are available in the outer SELECT with an alias.
        Expression lineage fields are added directly to the outer
        SELECT since they don't reference source columns.

        Returns:
            A tuple of (cte_extra_fields, outer_template_expressions).
        """
        if target_structure is None:
            return [], []

        target_type = target_structure.structure_type
        cte_extra_fields: list[str] = []
        cte_source_fields: set[str] = set(already_mapped_fields)
        outer_template_expressions: list[str] = []

        for template in target_structure.templates:
            for field_template in template.field_templates:
                lineage = field_template.lineage
                if lineage is None:
                    continue
                field_name = field_template.field.name
                if field_name in already_mapped_fields:
                    continue

                rule = lineage.resolve_for_target_type(target_type)
                if rule.expression is not None:
                    outer_template_expressions.append(
                        f"{rule.expression} AS {field_name}",
                    )
                elif rule.source_characterisation is not None:
                    source_field = find_source_field_by_characterisation(
                        source_structures=source_structures,
                        characterisation=rule.source_characterisation,
                    )
                    if source_field not in cte_source_fields:
                        cte_extra_fields.append(source_field)
                        cte_source_fields.add(source_field)

                    if source_field == field_name:
                        outer_template_expressions.append(source_field)
                    else:
                        outer_template_expressions.append(
                            f"{source_field} AS {field_name}",
                        )

                already_mapped_fields.add(field_name)

        return cte_extra_fields, outer_template_expressions

    def _resolve_unique_key_field_names(
        self,
        source_structure: Structure,
    ) -> list[str]:
        """Resolve unique key fields from configured characterisation or defaults.

        When a key_characterisation parameter is set in the config,
        uses that characterisation directly. Otherwise falls back to
        the functional_key characterisation.
        """
        key_characterisation = self._get_parameter("key_characterisation")
        if key_characterisation is not None:
            return self._resolve_fields_from_characterisation(
                source_structure=source_structure,
                characterisation=key_characterisation,
            )

        return self._resolve_fields_from_characterisation(
            source_structure=source_structure,
            characterisation=StructureCharacterisationDefinitionNames.FUNCTIONAL_KEY,
        )

    def _resolve_fields_from_characterisation(
        self,
        source_structure: Structure,
        characterisation: str,
    ) -> list[str]:
        """Resolve field names from a structure characterisation."""
        structure_char = source_structure.get_characterisation(
            characterisation,
        )
        if structure_char is None or not structure_char.linked_fields:
            raise ValueError(
                f"Structure '{source_structure.name}' has no "
                f"'{characterisation}' characterisation defined"
            )
        fields = source_structure.get_fields_based_on_names(
            structure_char.linked_fields,
        )
        return [field.name for field in fields]
