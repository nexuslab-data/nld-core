from __future__ import annotations

from typing import Any

from nld.connector.base import SQLConnectorStructureReader
from nld.connector.base.structure_reader import (
    normalize_column_default,
    normalize_structure_type,
)
from nld.connector.postgresql.connector_definition import (
    POSTGRESQL_CONNECTOR_DEFINITION,
)
from nld.connector.postgresql.engine.psycopg2.connector import Psycopg2SQLConnector
from nld.connector.postgresql.postgresql_structure import PostgreSQLStructure
from nld.connector.postgresql.sqlglot.ddl import PostgreSQLSqlglotDDLBuilder
from nld.exceptions import NldRuntimeException
from nld.structure import (
    Field,
    FieldCharacterisationDefinitionNames,
    Structure,
    StructureCharacterisation,
    StructureCharacterisationDefinitionNames,
)


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

    @property
    def _ddl_builder(self) -> PostgreSQLSqlglotDDLBuilder:
        """The builder owning every SQL string the reader executes."""
        return PostgreSQLSqlglotDDLBuilder()

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
        # Get all tables/views matching the filter (also carries table_type,
        # which the 4 detail queries below don't return)
        tables = self._get_tables_and_views(schema, object_name)

        if not tables:
            return []

        # Fetch all metadata at once for all tables, applying the same
        # filter inline rather than re-deriving it from `tables` above
        all_columns = self._get_all_columns(schema, object_name)
        all_indexes = self._get_all_indexes(schema, object_name)
        all_pk_columns = self._get_all_primary_key_columns(schema, object_name)
        all_unique_constraints = self._get_all_unique_constraints(schema, object_name)

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
        query = self._ddl_builder.build_tables_and_views_query(
            excluded_schemas=self.EXCLUDED_SCHEMAS,
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
        schema: str | None,
        object_name: str | None,
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        """Retrieve columns for all tables matching the filter at once.

        Args:
            schema: Optional schema name to filter by.
            object_name: Optional table/view name to filter by.

        Returns:
            Dict mapping (schema, table_name) to list of column metadata.
        """
        query = self._ddl_builder.build_table_columns_query(
            excluded_schemas=self.EXCLUDED_SCHEMAS,
            schema=schema,
            object_name=object_name,
        )
        result = self._connector.execute_query(query)
        df = result.get_result_df()

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
        self,
        schema: str | None,
        object_name: str | None,
    ) -> dict[tuple[str, str], tuple[str, list[str]]]:
        """Retrieve primary key constraint name and columns for the filtered tables.

        Args:
            schema: Optional schema name to filter by.
            object_name: Optional table/view name to filter by.

        Returns:
            Dict mapping (schema, table_name) to (constraint_name, column_names).
        """
        query = self._ddl_builder.build_primary_key_columns_query(
            excluded_schemas=self.EXCLUDED_SCHEMAS,
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

    def _get_all_unique_constraints(
        self,
        schema: str | None,
        object_name: str | None,
    ) -> dict[tuple[str, str], dict[str, list[str]]]:
        """Retrieve unique constraints for all tables matching the filter at once.

        Args:
            schema: Optional schema name to filter by.
            object_name: Optional table/view name to filter by.

        Returns:
            Dict mapping (schema, table_name) to dict of constraint_name -> columns.
        """
        query = self._ddl_builder.build_unique_constraints_query(
            excluded_schemas=self.EXCLUDED_SCHEMAS,
            schema=schema,
            object_name=object_name,
        )
        result = self._connector.execute_query(query)
        df = result.get_result_df()

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
        self,
        schema: str | None,
        object_name: str | None,
    ) -> dict[tuple[str, str], dict[str, list[str]]]:
        """Retrieve non-constraint indexes for all tables matching the filter.

        Queries pg_catalog to find indexes that are not backing a
        PRIMARY KEY or UNIQUE constraint. Expression indexes (where
        the indexed expression is not a simple column) are excluded.

        Args:
            schema: Optional schema name to filter by.
            object_name: Optional table/view name to filter by.

        Returns:
            Dict mapping (schema, table_name) to dict of
            index_name -> column names.
        """
        query = self._ddl_builder.build_table_indexes_query(
            excluded_schemas=self.EXCLUDED_SCHEMAS,
            schema=schema,
            object_name=object_name,
        )
        result = self._connector.execute_query(query)
        df = result.get_result_df()

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
        table_type = normalize_structure_type(table_info["table_type"])

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
            and not POSTGRESQL_CONNECTOR_DEFINITION.has_fixed_precision(data_type)
        ):
            precision = int(num_precision)

        # Build field
        field = Field(
            name=column_name,
            data_type=data_type,
            length=length,
            precision=precision,
            default_value=normalize_column_default(
                raw_default=column_info["column_default"],
            ),
        )

        # Add mandatory characterisation if NOT NULL
        if is_nullable == "NO":
            field.add_characterisation(FieldCharacterisationDefinitionNames.MANDATORY)

        return field

    def _normalize_data_type(self, pg_type: str) -> str:
        """Uppercase the catalog data type, without aliasing.

        Reader-level aliasing (``INTEGER`` -> ``INT``) caused false
        diffs whenever the declared spelling differed from the alias;
        both sides canonicalize through
        ``normalize_comparable_data_type`` instead, so the reader
        reports the catalog spelling verbatim.
        """
        return pg_type.upper() if pg_type else ""

    def get_dependent_views(
        self,
        schema: str,
        object_name: str,
    ) -> list[str]:
        """Return the views of the schema directly depending on an object.

        Uses the pg_depend catalog through the view rewrite rules —
        the reason PostgreSQL blocks ALTER on a referenced column.
        Cross-schema dependents are out of scope for now.
        """
        query = self._ddl_builder.build_dependent_views_query(
            schema=schema,
            object_name=object_name,
        )
        result = self._connector.execute_query(query)
        records = result.get_result_records()
        return sorted(record["view_name"] for record in records)

    def get_all_dependent_views(
        self,
        schema: str,
    ) -> dict[str, list[str]]:
        """Return every direct view-dependency edge in the schema, batched.

        One query returns the source→view edge for every table/view
        pair in the schema; the BFS in ``find_dependent_views`` walks
        this in-memory graph instead of issuing one query per node.
        """
        query = self._ddl_builder.build_all_dependent_views_query(schema=schema)
        result = self._connector.execute_query(query)
        records = result.get_result_records()
        graph: dict[str, list[str]] = {}
        for record in records:
            graph.setdefault(record["source_name"], []).append(record["view_name"])
        for source_name, view_names in graph.items():
            graph[source_name] = sorted(view_names)
        return graph
