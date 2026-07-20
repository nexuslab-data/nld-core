from __future__ import annotations

from typing import Any

import sqlglot

from nld.connector.base import SQLConnectorStructureReader
from nld.connector.base.structure_reader import (
    normalize_structure_type,
    parse_view_dependencies,
)
from nld.connector.duckdb.connector_definition import DUCKDB_CONNECTOR_DEFINITION
from nld.connector.duckdb.duckdb_structure import DuckDBStructure
from nld.connector.duckdb.engine.duckdb_native.connector import DuckDBSQLConnector
from nld.connector.duckdb.sqlglot.ddl import DuckDBSqlglotDDLBuilder
from nld.structure import (
    Field,
    FieldCharacterisationDefinitionNames,
    Structure,
    StructureCharacterisation,
    StructureCharacterisationDefinitionNames,
)


class DuckDBStructureReader(SQLConnectorStructureReader[DuckDBSQLConnector]):
    """Service to extract database structure from DuckDB.

    Queries the information_schema to extract metadata about
    tables, views, columns, primary keys, and unique constraints.
    """

    EXCLUDED_SCHEMAS = ("information_schema", "pg_catalog", "system")

    @property
    def active_database(self) -> str | None:
        """Get the active database name from the connection."""
        return self._connector.get_active_database()

    @property
    def _ddl_builder(self) -> DuckDBSqlglotDDLBuilder:
        """The builder owning every catalog query this reader runs."""
        return DuckDBSqlglotDDLBuilder()

    def extract_structures(
        self,
        database: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
        **kwargs: Any,
    ) -> list[Structure]:
        """Extract structures (tables/views) from DuckDB.

        Args:
            database: Optional catalog name to extract from.
                Defaults to the active catalog (``current_catalog()``).
            schema: Optional schema name to filter by.
            object_name: Optional table/view name to filter by.

        Returns:
            List of Structure objects representing tables and views.
        """
        catalog = database or self.active_database
        tables = self._get_tables_and_views(catalog, schema, object_name)

        if not tables:
            return []

        # The four detail queries apply the same catalog filter as the
        # listing and build target_tables as an inline subquery — no
        # VALUES list re-serialized from a prior round trip.
        all_columns = self._get_all_columns(catalog, schema, object_name)
        all_pk_columns = self._get_all_primary_key_columns(
            catalog,
            schema,
            object_name,
        )
        # DuckDB creates UNIQUE via CREATE UNIQUE INDEX (not ADD CONSTRAINT).
        # information_schema.table_constraints does NOT list these, so we
        # read them from duckdb_indexes() instead.
        all_unique_constraints = self._get_all_unique_indexes(
            catalog,
            schema,
            object_name,
        )
        all_indexes = self._get_all_indexes(catalog, schema, object_name)

        structures: list[Structure] = []
        for table_info in tables:
            table_schema = table_info["table_schema"]
            table_name = table_info["table_name"]
            key = (table_schema, table_name)

            columns = all_columns.get(key, [])
            pk_info = all_pk_columns.get(key)
            pk_constraint_name = pk_info[0] if pk_info else None
            pk_columns = pk_info[1] if pk_info else []
            unique_constraints = all_unique_constraints.get(key, {})
            indexes = all_indexes.get(key, {})

            structure = self._build_structure(
                table_info,
                columns,
                pk_columns,
                unique_constraints,
                indexes=indexes,
                pk_constraint_name=pk_constraint_name,
            )
            structures.append(structure)

        return structures

    def get_all_dependent_views(
        self,
        schema: str,
    ) -> dict[str, list[str]]:
        """Return every direct view-dependency edge, parsed from definitions.

        DuckDB has no queryable view-dependency catalog (views are
        late-binding), so the edges are derived by parsing the
        definitions ``duckdb_views()`` returns.
        """
        query = self._ddl_builder.build_views_query(schema=schema)
        result = self._connector.execute_query(query)
        result.raise_on_error(f"DuckDB view listing failed for schema {schema}")
        df = result.get_result_df()
        if df.empty:
            return {}
        view_definitions = {
            str(row["view_name"]).lower(): str(row["sql"])
            for _, row in df.iterrows()
            if row.get("sql")
        }
        return parse_view_dependencies(
            view_definitions=view_definitions,
            dialect="duckdb",
        )

    def _get_tables_and_views(
        self,
        catalog: str | None,
        schema: str | None,
        object_name: str | None,
    ) -> list[dict[str, Any]]:
        """Retrieve the list of tables and views for a catalog."""
        query = self._ddl_builder.build_tables_and_views_query(
            excluded_schemas=self.EXCLUDED_SCHEMAS,
            catalog=catalog,
            schema=schema,
            object_name=object_name,
        )
        result = self._connector.execute_query(query)
        df = result.get_result_df()
        if df.empty:
            return []
        return df.to_dict("records")  # type: ignore[return-value]

    def _get_all_columns(
        self,
        catalog: str | None,
        schema: str | None,
        object_name: str | None,
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        """Retrieve columns for all filtered tables at once."""
        query = self._ddl_builder.build_table_columns_query(
            excluded_schemas=self.EXCLUDED_SCHEMAS,
            catalog=catalog,
            schema=schema,
            object_name=object_name,
        )
        result = self._connector.execute_query(query)
        df = result.get_result_df()

        columns_by_table: dict[tuple[str, str], list[dict[str, Any]]] = {}
        rows: list[dict[str, Any]] = df.to_dict("records")  # type: ignore[assignment]
        for row in rows:
            key = (row["table_schema"], row["table_name"])
            if key not in columns_by_table:
                columns_by_table[key] = []
            columns_by_table[key].append(row)

        return columns_by_table

    def _get_all_primary_key_columns(
        self,
        catalog: str | None,
        schema: str | None,
        object_name: str | None,
    ) -> dict[tuple[str, str], tuple[str, list[str]]]:
        """Retrieve primary key constraint name and columns."""
        query = self._ddl_builder.build_primary_key_columns_query(
            excluded_schemas=self.EXCLUDED_SCHEMAS,
            catalog=catalog,
            schema=schema,
            object_name=object_name,
        )
        result = self._connector.execute_query(query)
        df = result.get_result_df()

        pk_by_table: dict[tuple[str, str], tuple[str, list[str]]] = {}
        for row in df.to_dict("records"):
            key = (row["table_schema"], row["table_name"])
            constraint_name = row["constraint_name"]
            if key not in pk_by_table:
                pk_by_table[key] = (constraint_name, [])
            pk_by_table[key][1].append(row["column_name"])

        return pk_by_table

    def _get_all_unique_indexes(
        self,
        catalog: str | None,
        schema: str | None,
        object_name: str | None,
    ) -> dict[tuple[str, str], dict[str, list[str]]]:
        """Retrieve unique indexes for all specified tables.

        In DuckDB, UNIQUE constraints are implemented as UNIQUE INDEX
        (via CREATE UNIQUE INDEX). They do NOT appear in
        information_schema.table_constraints. This method reads them
        from duckdb_indexes() where is_unique is true.
        """
        query = self._ddl_builder.build_unique_indexes_query(
            excluded_schemas=self.EXCLUDED_SCHEMAS,
            catalog=catalog,
            schema=schema,
            object_name=object_name,
        )
        result = self._connector.execute_query(query)
        df = result.get_result_df()

        unique_by_table: dict[tuple[str, str], dict[str, list[str]]] = {}
        for row in df.to_dict("records"):
            key = (row["table_schema"], row["table_name"])
            index_name = row["index_name"]
            columns = self._extract_columns_from_index_sql(
                row.get("index_sql"),
            )
            if not columns:
                continue
            if key not in unique_by_table:
                unique_by_table[key] = {}
            unique_by_table[key][index_name] = columns

        return unique_by_table

    def _get_all_indexes(
        self,
        catalog: str | None,
        schema: str | None,
        object_name: str | None,
    ) -> dict[tuple[str, str], dict[str, list[str]]]:
        """Retrieve non-constraint indexes for all specified tables.

        Uses DuckDB's duckdb_indexes() function to find indexes
        that are not backing a PRIMARY KEY or UNIQUE constraint.
        """
        query = self._ddl_builder.build_table_indexes_query(
            excluded_schemas=self.EXCLUDED_SCHEMAS,
            catalog=catalog,
            schema=schema,
            object_name=object_name,
        )
        result = self._connector.execute_query(query)
        df = result.get_result_df()

        indexes_by_table: dict[tuple[str, str], dict[str, list[str]]] = {}
        for row in df.to_dict("records"):
            key = (row["table_schema"], row["table_name"])
            index_name = row["index_name"]
            columns = self._extract_columns_from_index_sql(
                row.get("index_sql"),
            )
            # Skip expression indexes or unparsable SQL where no
            # plain column names could be extracted.  Materializing
            # a characterisation with empty linked_fields would
            # misrepresent the index.
            if not columns:
                continue
            if key not in indexes_by_table:
                indexes_by_table[key] = {}
            indexes_by_table[key][index_name] = columns

        return indexes_by_table

    @staticmethod
    def _extract_columns_from_index_sql(
        index_sql: str | None,
    ) -> list[str]:
        """Extract plain column names from a CREATE INDEX SQL statement.

        Returns the column list ONLY if every indexed element is a
        plain column reference.  If any element is an expression
        (function, arithmetic, cast, etc.), the entire index is
        skipped by returning an empty list.  Returning a partial
        column list would misrepresent the index semantics.

        Args:
            index_sql: The CREATE INDEX SQL from duckdb_indexes().sql.

        Returns:
            List of column names if the index is purely column-based,
            or an empty list otherwise.
        """
        if not index_sql:
            return []
        try:
            parsed = sqlglot.parse_one(index_sql, dialect="duckdb")

            # Count total indexed elements (Ordered nodes inside
            # the Index) and plain-column elements.
            total_elements = 0
            columns: list[str] = []
            for ordered in parsed.find_all(sqlglot.exp.Ordered):
                total_elements += 1
                child = ordered.this
                if isinstance(child, sqlglot.exp.Column):
                    columns.append(child.name)

            # If any element was non-column, skip the whole index
            if len(columns) != total_elements:
                return []
            return columns
        except sqlglot.errors.ParseError:
            return []

    def _build_structure(
        self,
        table_info: dict[str, Any],
        columns: list[dict[str, Any]],
        pk_columns: list[str],
        unique_constraints: dict[str, list[str]],
        indexes: dict[str, list[str]] | None = None,
        pk_constraint_name: str | None = None,
    ) -> DuckDBStructure:
        """Build a Structure object from extracted metadata."""
        table_schema = table_info["table_schema"]
        table_name = table_info["table_name"]
        table_type = normalize_structure_type(table_info["table_type"])

        fields: dict[str, Field] = {}
        for col in columns:
            field = self._build_field(col)
            fields[field.name] = field

        characterisations: list[StructureCharacterisation] = []

        if pk_columns:
            # DuckDB auto-renames PK constraints to <table>_<col>_pkey
            # regardless of the name supplied in DDL.  Use a canonical
            # name so the diff engine sees the same name on every
            # read cycle and in YAML structure definitions.
            characterisations.append(
                StructureCharacterisation(
                    name=f"pk_{table_name.lower()}",
                    characterisation=StructureCharacterisationDefinitionNames.PRIMARY_KEY,
                    linked_fields=pk_columns,
                )
            )

        if indexes:
            for index_name, index_columns in indexes.items():
                characterisations.append(
                    StructureCharacterisation(
                        name=index_name,
                        characterisation=StructureCharacterisationDefinitionNames.INDEX,
                        linked_fields=index_columns,
                    )
                )

        for constraint_name, constraint_columns in unique_constraints.items():
            characterisations.append(
                StructureCharacterisation(
                    name=constraint_name,
                    characterisation=StructureCharacterisationDefinitionNames.UNIQUE,
                    linked_fields=constraint_columns,
                )
            )

        table_catalog = table_info.get("table_catalog", self.active_database or "")

        return DuckDBStructure(
            name=table_name,
            structure_type=table_type,
            connector_type="duckdb",
            properties={
                "database": table_catalog,
                "schema": table_schema,
            },
            fields=fields,
            characterisations=characterisations,
        )

    def _build_field(self, column_info: dict[str, Any]) -> Field:
        """Build a Field object from column metadata."""
        import pandas as pd

        column_name = column_info["column_name"]
        data_type = self._normalize_data_type(column_info["data_type"])
        is_nullable = column_info["is_nullable"]

        length = 0
        precision = 0

        char_max_length = column_info["character_maximum_length"]
        num_precision = column_info["numeric_precision"]
        num_scale = column_info.get("numeric_scale")

        if char_max_length and not pd.isna(char_max_length):
            length = int(char_max_length)
        elif (
            num_precision
            and not pd.isna(num_precision)
            and not DUCKDB_CONNECTOR_DEFINITION.has_fixed_precision(data_type)
        ):
            # For DECIMAL/NUMERIC: precision is total digits, scale is
            # fractional digits.  Both must be preserved even when scale
            # is 0 (e.g. DECIMAL(10,0) -> length=10, precision=0).
            if num_scale is not None and not pd.isna(num_scale):
                length = int(num_precision)
                precision = int(num_scale)
            else:
                precision = int(num_precision)

        field = Field(
            name=column_name,
            data_type=data_type,
            length=length,
            precision=precision,
        )

        if is_nullable == "NO":
            field.add_characterisation(FieldCharacterisationDefinitionNames.MANDATORY)

        return field

    def _normalize_data_type(self, duckdb_type: str) -> str:
        """Normalize a DuckDB data type to its canonical form.

        DuckDB normalises all text types to VARCHAR in
        information_schema; align YAML types to match readback by
        delegating to ``DuckDBSqlglotDDLBuilder``, the single owner
        of that string-type canonicalization (it applies the same
        normalization when emitting DDL, so the read-back type and
        the emitted type never diverge).

        No other aliases — DuckDB returns canonical type names.
        Do NOT normalise INTEGER to INT: that would cause false
        diffs because the framework diff engine compares types
        as exact strings.
        """
        upper_type = duckdb_type.upper() if duckdb_type else ""
        return DuckDBSqlglotDDLBuilder.normalize_string_type(data_type=upper_type)
