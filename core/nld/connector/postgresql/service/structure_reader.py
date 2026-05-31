from __future__ import annotations

from typing import Any

from nld.connector.base import QueryWrapper, SQLConnectorStructureReader
from nld.connector.postgresql.engine.psycopg2.connector import Psycopg2SQLConnector
from nld.connector.postgresql.postgresql_structure import PostgreSQLStructure
from nld.exceptions import NldRuntimeException
from nld.structure import (
    Field,
    FieldCharacterisationDefinitionNames,
    Structure,
    StructureCharacterisation,
    StructureCharacterisationDefinitionNames,
)


def _escape_sql_literal(value: str) -> str:
    """Escape a SQL string literal to prevent SQL injection.

    Doubles any single quotes in the value, which is the standard
    SQL escaping mechanism for string literals.

    Args:
        value: The string value to escape.

    Returns:
        The escaped value safe for use in SQL string literals.
    """
    return value.replace("'", "''")


class PostgreSQLStructureReader(SQLConnectorStructureReader[Psycopg2SQLConnector]):
    """Service to extract database structure from PostgreSQL.

    This service queries the information_schema to extract metadata about
    tables, views, columns, primary keys, and unique constraints.

    Example:
        >>> reader = PostgreSQLStructureReader(connector)
        >>> structures = reader.extract_structures(schema="public")
        >>> for structure in structures:
        ...     print(structure.name, structure.structure_type)
    """

    # System schemas to exclude from extraction
    EXCLUDED_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")

    @property
    def active_database(self) -> str | None:
        """Get the active database name from the connection."""
        return self._connector.get_active_database()

    def extract_structures(
        self,
        database: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
        **kwargs: Any,
    ) -> list[Structure]:
        """Extract structures (tables/views) from PostgreSQL.

        Args:
            database: Optional database name. When provided, validates
                it matches the active database since PostgreSQL
                connections are bound to a single database.
            schema: Optional schema name to filter by.
            object_name: Optional table/view name to filter by.

        Returns:
            List of Structure objects representing tables and views.

        Raises:
            NldRuntimeException: If the provided database does not
                match the active database.
        """
        if database is not None and database != self.active_database:
            msg = (
                f"Connection is bound to database '{self.active_database}', "
                f"cannot query '{database}'"
            )
            raise NldRuntimeException(msg)
        # Get all tables/views matching the filter
        tables = self._get_tables_and_views(schema, object_name)

        if not tables:
            return []

        # Build filter for bulk queries
        table_keys = [(t["table_schema"], t["table_name"]) for t in tables]

        # Fetch all metadata at once for all tables
        all_columns = self._get_all_columns(table_keys)
        all_indexes = self._get_all_indexes(table_keys)
        all_pk_columns = self._get_all_primary_key_columns(table_keys)
        all_unique_constraints = self._get_all_unique_constraints(table_keys)

        # Build structures from pre-fetched data
        structures: list[Structure] = []
        for table_info in tables:
            table_schema = table_info["table_schema"]
            table_name = table_info["table_name"]
            key = (table_schema, table_name)

            columns = all_columns.get(key, [])
            indexes = all_indexes.get(key, {})
            pk_info = all_pk_columns.get(key)
            pk_constraint_name = pk_info[0] if pk_info else None
            pk_columns = pk_info[1] if pk_info else []
            unique_constraints = all_unique_constraints.get(key, {})

            structure = self._build_structure(
                table_info,
                columns,
                pk_columns,
                unique_constraints,
                indexes,
                pk_constraint_name=pk_constraint_name,
            )
            structures.append(structure)

        return structures

    def _build_values_clause(self, table_keys: list[tuple[str, str]]) -> str:
        """Build a VALUES clause for filtering with escaped identifiers.

        The values come from information_schema (database metadata) so they
        are trusted, but we escape them to handle edge cases like identifiers
        containing quotes.

        Args:
            table_keys: List of (schema, table_name) tuples.

        Returns:
            A VALUES clause string like "VALUES ('s1', 't1'), ('s2', 't2')".
        """
        values_parts = [
            f"('{_escape_sql_literal(schema)}', '{_escape_sql_literal(table)}')"
            for schema, table in table_keys
        ]
        return "VALUES " + ", ".join(values_parts)

    def _get_tables_and_views(
        self,
        schema: str | None,
        object_name: str | None,
    ) -> list[dict[str, Any]]:
        """Retrieve the list of tables and views.

        Args:
            schema: Optional schema name to filter by.
            object_name: Optional table/view name to filter by.

        Returns:
            List of dicts with table_schema, table_name, table_type.
        """
        excluded_schemas = ", ".join(f"'{s}'" for s in self.EXCLUDED_SCHEMAS)

        query = f"""
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema NOT IN ({excluded_schemas})
            {{% if schema %}}AND table_schema = '{{{{ schema }}}}'{{% endif %}}
            {{% if object_name %}}AND table_name = '{{{{ object_name }}}}'{{% endif %}}
            ORDER BY table_schema, table_name
        """

        params: dict[str, Any] = {}
        if schema:
            params["schema"] = schema
        if object_name:
            params["object_name"] = object_name

        result = self._connector.execute_query(QueryWrapper(query=query, params=params))
        df = result.get_output_data_as_df()
        if df.empty:
            return []
        return df.to_dict("records")  # type: ignore[return-value]

    def _get_all_columns(
        self, table_keys: list[tuple[str, str]]
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        """Retrieve columns for all specified tables at once.

        Args:
            table_keys: List of (schema, table_name) tuples.

        Returns:
            Dict mapping (schema, table_name) to list of column metadata.
        """
        if not table_keys:
            return {}

        values_clause = self._build_values_clause(table_keys)

        query = f"""
            WITH target_tables (schema_name, table_name) AS (
                {values_clause}
            )
            SELECT
                c.table_schema,
                c.table_name,
                c.column_name,
                c.data_type,
                c.character_maximum_length,
                c.numeric_precision,
                c.numeric_scale,
                c.is_nullable,
                c.column_default
            FROM information_schema.columns c
            INNER JOIN target_tables t
                ON c.table_schema = t.schema_name
                AND c.table_name = t.table_name
            ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """

        result = self._connector.execute_query(QueryWrapper(query=query))
        df = result.get_output_data_as_df()

        # Group by (schema, table_name)
        columns_by_table: dict[tuple[str, str], list[dict[str, Any]]] = {}
        rows: list[dict[str, Any]] = df.to_dict("records")  # type: ignore[assignment]
        for row in rows:
            key = (row["table_schema"], row["table_name"])
            if key not in columns_by_table:
                columns_by_table[key] = []
            columns_by_table[key].append(row)

        return columns_by_table

    def _get_all_primary_key_columns(
        self, table_keys: list[tuple[str, str]]
    ) -> dict[tuple[str, str], tuple[str, list[str]]]:
        """Retrieve primary key constraint name and columns for all specified tables.

        Args:
            table_keys: List of (schema, table_name) tuples.

        Returns:
            Dict mapping (schema, table_name) to (constraint_name, column_names).
        """
        if not table_keys:
            return {}

        values_clause = self._build_values_clause(table_keys)

        query = f"""
            WITH target_tables (schema_name, table_name) AS (
                {values_clause}
            )
            SELECT tc.table_schema, tc.table_name, tc.constraint_name, kcu.column_name
            FROM information_schema.table_constraints tc
            INNER JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.constraint_schema = kcu.constraint_schema
            INNER JOIN target_tables t
                ON tc.table_schema = t.schema_name
                AND tc.table_name = t.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
            ORDER BY tc.table_schema, tc.table_name, kcu.ordinal_position
        """

        result = self._connector.execute_query(QueryWrapper(query=query))
        df = result.get_output_data_as_df()

        pk_by_table: dict[tuple[str, str], tuple[str, list[str]]] = {}
        for row in df.to_dict("records"):
            key = (row["table_schema"], row["table_name"])
            constraint_name = row["constraint_name"]
            if key not in pk_by_table:
                pk_by_table[key] = (constraint_name, [])
            pk_by_table[key][1].append(row["column_name"])

        return pk_by_table

    def _get_all_unique_constraints(
        self, table_keys: list[tuple[str, str]]
    ) -> dict[tuple[str, str], dict[str, list[str]]]:
        """Retrieve unique constraints for all specified tables at once.

        Args:
            table_keys: List of (schema, table_name) tuples.

        Returns:
            Dict mapping (schema, table_name) to dict of constraint_name -> columns.
        """
        if not table_keys:
            return {}

        values_clause = self._build_values_clause(table_keys)

        query = f"""
            WITH target_tables (schema_name, table_name) AS (
                {values_clause}
            )
            SELECT tc.table_schema, tc.table_name, tc.constraint_name, kcu.column_name
            FROM information_schema.table_constraints tc
            INNER JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.constraint_schema = kcu.constraint_schema
            INNER JOIN target_tables t
                ON tc.table_schema = t.schema_name
                AND tc.table_name = t.table_name
            WHERE tc.constraint_type = 'UNIQUE'
            ORDER BY tc.table_schema, tc.table_name, tc.constraint_name,
                kcu.ordinal_position
        """

        result = self._connector.execute_query(QueryWrapper(query=query))
        df = result.get_output_data_as_df()

        # Group by (schema, table_name) then by constraint_name
        unique_by_table: dict[tuple[str, str], dict[str, list[str]]] = {}
        for row in df.to_dict("records"):
            key = (row["table_schema"], row["table_name"])
            constraint_name = row["constraint_name"]
            column_name = row["column_name"]

            if key not in unique_by_table:
                unique_by_table[key] = {}
            if constraint_name not in unique_by_table[key]:
                unique_by_table[key][constraint_name] = []
            unique_by_table[key][constraint_name].append(column_name)

        return unique_by_table

    def _get_all_indexes(
        self, table_keys: list[tuple[str, str]]
    ) -> dict[tuple[str, str], dict[str, list[str]]]:
        """Retrieve non-constraint indexes for all specified tables at once.

        Queries pg_catalog to find indexes that are not backing a
        PRIMARY KEY or UNIQUE constraint. Expression indexes (where
        the indexed expression is not a simple column) are excluded.

        Args:
            table_keys: List of (schema, table_name) tuples.

        Returns:
            Dict mapping (schema, table_name) to dict of
            index_name -> column names.
        """
        if not table_keys:
            return {}

        values_clause = self._build_values_clause(table_keys)

        query = f"""
            WITH target_tables (schema_name, table_name) AS (
                {values_clause}
            )
            SELECT
                n.nspname AS table_schema,
                t.relname AS table_name,
                i.relname AS index_name,
                a.attname AS column_name,
                array_position(ix.indkey, a.attnum) AS col_position
            FROM pg_catalog.pg_index ix
            INNER JOIN pg_catalog.pg_class t
                ON t.oid = ix.indrelid
            INNER JOIN pg_catalog.pg_class i
                ON i.oid = ix.indexrelid
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = t.relnamespace
            INNER JOIN pg_catalog.pg_attribute a
                ON a.attrelid = t.oid
                AND a.attnum = ANY(ix.indkey)
                AND a.attnum > 0
            INNER JOIN target_tables tt
                ON n.nspname = tt.schema_name
                AND t.relname = tt.table_name
            LEFT JOIN pg_catalog.pg_constraint c
                ON c.conindid = ix.indexrelid
            WHERE NOT ix.indisunique
                AND NOT ix.indisprimary
                AND c.oid IS NULL
            ORDER BY n.nspname, t.relname, i.relname,
                array_position(ix.indkey, a.attnum)
        """

        result = self._connector.execute_query(QueryWrapper(query=query))
        df = result.get_output_data_as_df()

        indexes_by_table: dict[tuple[str, str], dict[str, list[str]]] = {}
        for row in df.to_dict("records"):
            key = (row["table_schema"], row["table_name"])
            index_name = row["index_name"]
            column_name = row["column_name"]

            if key not in indexes_by_table:
                indexes_by_table[key] = {}
            if index_name not in indexes_by_table[key]:
                indexes_by_table[key][index_name] = []
            indexes_by_table[key][index_name].append(column_name)

        return indexes_by_table

    def _build_structure(
        self,
        table_info: dict[str, Any],
        columns: list[dict[str, Any]],
        pk_columns: list[str],
        unique_constraints: dict[str, list[str]],
        indexes: dict[str, list[str]] | None = None,
        pk_constraint_name: str | None = None,
    ) -> PostgreSQLStructure:
        """Build a Structure object from extracted metadata.

        Args:
            table_info: Dict with table_schema, table_name, table_type.
            columns: List of column metadata dicts.
            pk_columns: List of primary key column names.
            unique_constraints: Dict of constraint_name -> column names.
            indexes: Dict of index_name -> column names for
                non-constraint indexes.
            pk_constraint_name: The actual constraint name from the database
                for the primary key. Falls back to the generic "primary_key"
                when not provided.

        Returns:
            A Structure object representing the table/view.
        """
        table_schema = table_info["table_schema"]
        table_name = table_info["table_name"]
        table_type = self._normalize_structure_type(table_info["table_type"])

        # Build fields
        fields: dict[str, Field] = {}
        for col in columns:
            field = self._build_field(col)
            fields[field.name] = field

        # Build structure characterisations
        characterisations: list[StructureCharacterisation] = []

        # Add primary key characterisation
        if pk_columns:
            characterisations.append(
                StructureCharacterisation(
                    name=pk_constraint_name or f"pk_{table_name.lower()}",
                    characterisation=StructureCharacterisationDefinitionNames.PRIMARY_KEY,
                    linked_fields=pk_columns,
                )
            )

        # Add index characterisations
        if indexes:
            for index_name, index_columns in indexes.items():
                characterisations.append(
                    StructureCharacterisation(
                        name=index_name,
                        characterisation=StructureCharacterisationDefinitionNames.INDEX,
                        linked_fields=index_columns,
                    )
                )

        # Add unique constraint characterisations
        for constraint_name, constraint_columns in unique_constraints.items():
            characterisations.append(
                StructureCharacterisation(
                    name=constraint_name,
                    characterisation=StructureCharacterisationDefinitionNames.UNIQUE,
                    linked_fields=constraint_columns,
                )
            )

        return PostgreSQLStructure(
            name=table_name,
            structure_type=table_type,
            connector_type="postgresql",
            properties={
                "database": self.active_database or "",
                "schema": table_schema,
            },
            fields=fields,
            characterisations=characterisations,
        )

    def _build_field(self, column_info: dict[str, Any]) -> Field:
        """Build a Field object from column metadata.

        Args:
            column_info: Dict with column metadata from information_schema.

        Returns:
            A Field object representing the column.
        """
        import pandas as pd

        column_name = column_info["column_name"]
        data_type = self._normalize_data_type(column_info["data_type"])
        is_nullable = column_info["is_nullable"]

        # Determine length/precision (handle NaN from DataFrame conversion)
        length = 0
        precision = 0

        char_max_length = column_info["character_maximum_length"]
        num_precision = column_info["numeric_precision"]

        if char_max_length and not pd.isna(char_max_length):
            length = int(char_max_length)
        elif (
            num_precision
            and not pd.isna(num_precision)
            and not self._has_fixed_precision(data_type)
        ):
            precision = int(num_precision)

        # Build field
        field = Field(
            name=column_name,
            data_type=data_type,
            length=length,
            precision=precision,
        )

        # Add mandatory characterisation if NOT NULL
        if is_nullable == "NO":
            field.add_characterisation(FieldCharacterisationDefinitionNames.MANDATORY)

        return field

    def _normalize_structure_type(self, raw_type: str) -> str:
        """Normalize a PostgreSQL structure type.

        Maps PostgreSQL information_schema type names to standard
        NLD structure types (e.g. "BASE TABLE" becomes "TABLE").

        Args:
            raw_type: The raw structure type from information_schema.

        Returns:
            Normalized structure type string.
        """
        pg_structure_type_mapping = {
            "BASE TABLE": "TABLE",
        }
        upper_type = raw_type.upper() if raw_type else ""
        return pg_structure_type_mapping.get(upper_type, upper_type)

    _PG_DATA_TYPE_ALIASES: dict[str, str] = {
        "INTEGER": "INT",
    }

    _PG_FIXED_PRECISION_TYPES: set[str] = {
        "BIGINT",
        "BOOLEAN",
        "DATE",
        "DOUBLE PRECISION",
        "INT",
        "INTEGER",
        "REAL",
        "SMALLINT",
        "TEXT",
    }

    def _normalize_data_type(self, pg_type: str) -> str:
        """Normalize a PostgreSQL data type to its canonical form.

        Maps information_schema type names to the standard forms
        used in structure YAML definitions. For example, "INTEGER"
        becomes "INT" and "TIMESTAMP WITHOUT TIME ZONE" becomes
        "TIMESTAMP".

        Args:
            pg_type: The PostgreSQL data type string.

        Returns:
            Normalized data type string.
        """
        upper_type = pg_type.upper() if pg_type else ""
        return self._PG_DATA_TYPE_ALIASES.get(upper_type, upper_type)

    def _has_fixed_precision(self, data_type: str) -> bool:
        """Check if a data type has a fixed precision that should not be reported."""
        return data_type.upper() in self._PG_FIXED_PRECISION_TYPES
