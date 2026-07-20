from nld.connector.bigquery.service.deploy_capabilities import (
    BIGQUERY_DEPLOY_CAPABILITIES,
)
from nld.connector.bigquery.sqlglot import BigQuerySqlglotDDLBuilder
from nld.structure.deploy.structure_diff import (
    DiffAction,
    FieldDiff,
    StructureDiff,
)
from nld.structure.deploy.structure_diff_ddl_statement_builder import (
    BaseStructureDiffDDLStatementBuilder,
    DDLStatement,
)
from nld.structure.structure.structure import Structure
from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder


class BigQueryStructureDiffDDLStatementBuilder(BaseStructureDiffDDLStatementBuilder):
    _TYPE_CHANGE_FALLBACK_DATA_TYPE = "STRING"
    """Generates BigQuery-specific DDL from structure diffs.

    BigQuery does not support indexes, unique constraints, or
    NOT NULL alterations via ALTER TABLE. Only column add, drop,
    and type changes are supported.
    """

    @property
    def dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        return BIGQUERY_DEPLOY_CAPABILITIES.dialect

    @property
    def _ddl_builder(self) -> BaseSqlglotDDLBuilder:
        """Use the BigQuery-specific DDL builder.

        The base implementation returns a generic ``BaseSqlglotDDLBuilder``
        keyed on the dialect, which would emit ``PRIMARY KEY (...)``
        without ``NOT ENFORCED`` and reject queries on
        ``information_schema.tables``. The BigQuery override fixes both.
        """
        return BigQuerySqlglotDDLBuilder()

    def build_create_table_statements(
        self,
        structure: Structure,
        schema_name: str,
    ) -> list[DDLStatement]:
        """Generate a CREATE TABLE statement for BigQuery."""
        columns = [
            (
                field.name,
                self._ddl_builder.build_type_expression(
                    data_type=field.data_type,
                    length=field.length,
                    precision=field.precision,
                ),
                field.is_mandatory(),
            )
            for field in structure.get_all_fields()
        ]

        primary_key_fields = self._get_primary_key_field_names(
            structure=structure,
        )

        sql = self._ddl_builder.build_create_table(
            schema=schema_name,
            table=structure.name,
            columns=columns,
            primary_key_fields=primary_key_fields,
        )

        table_path = f"{schema_name}.{structure.name}"
        return [
            DDLStatement(
                sql=sql,
                description=f"Create table {table_path}",
            )
        ]

    def build_alter_statements(
        self,
        diff: StructureDiff,
        schema_name: str,
    ) -> list[DDLStatement]:
        """Generate ALTER TABLE statements from a structure diff."""
        statements: list[DDLStatement] = []

        for field_diff in diff.field_diffs:
            statements.extend(
                self._generate_field_alter(
                    field_diff=field_diff,
                    schema_name=schema_name,
                    table_name=diff.structure_name,
                )
            )

        return statements

    def _generate_field_alter(
        self,
        field_diff: FieldDiff,
        schema_name: str,
        table_name: str,
    ) -> list[DDLStatement]:
        """Generate ALTER statements for a single field diff."""
        statements: list[DDLStatement] = []

        if field_diff.action == DiffAction.ADD:
            # Preserve length / precision on ADD so that e.g.
            # ``STRING(64)`` or ``NUMERIC(10, 2)`` do not deploy as
            # bare ``STRING`` / ``NUMERIC`` and cause silent schema
            # divergence vs the declared structure.
            add_type = self._resolve_type_expression(field_diff=field_diff) or "STRING"
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_alter_add_column(
                        schema=schema_name,
                        table=table_name,
                        column_name=field_diff.field_name,
                        data_type=add_type,
                    ),
                    description=f"Add column {field_diff.field_name}",
                )
            )

        elif field_diff.action == DiffAction.DROP:
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_alter_drop_column(
                        schema=schema_name,
                        table=table_name,
                        column_name=field_diff.field_name,
                    ),
                    description=f"Drop column {field_diff.field_name}",
                )
            )

        elif field_diff.action == DiffAction.MODIFY:
            type_expr = self._resolve_type_expression(field_diff=field_diff)
            if type_expr is not None:
                statements.append(
                    DDLStatement(
                        sql=self._ddl_builder.build_alter_column_type(
                            schema=schema_name,
                            table=table_name,
                            column_name=field_diff.field_name,
                            new_type=type_expr,
                        ),
                        description=(
                            f"Change type of {field_diff.field_name} "
                            f"from {field_diff.data_type_from} to {type_expr}"
                        ),
                    )
                )

        return statements
