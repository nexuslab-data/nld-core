from typing import Any

import pandas as pd

from nld.connector.base.exceptions import QueryExecutionException
from nld.connector.base.structure_reader import (
    SQLConnectorStructureReader,
    normalize_column_default,
    parse_view_dependencies,
)
from nld.connector.snowflake.snowflake_connector import SnowflakeConnector
from nld.connector.snowflake.snowflake_structure import SnowflakeStructure
from nld.connector.snowflake.sqlglot.ddl import SnowflakeSqlglotDDLBuilder
from nld.structure import Structure
from nld.structure.field.field import Field
from nld.structure.structure.structure_characterisation import (
    StructureCharacterisation,
)
from nld.structure.structure.structure_characterisation_def import (
    StructureCharacterisationDefinitionNames,
)

# SHOW commands return at most 10K rows; a result at exactly the cap
# is almost certainly truncated.
_SHOW_ROW_CAP = 10_000


def _guard_show_row_cap(df: pd.DataFrame, query: str) -> None:
    """Fail loudly when a SHOW command hits Snowflake's row cap.

    Treating a truncated listing as complete would make the deploy
    plan CREATEs for the missing objects (or drop their keys).
    Callers must narrow the scope or move to a RESULT_SCAN pagination
    strategy before this ever triggers.
    """
    if len(df) >= _SHOW_ROW_CAP:
        raise QueryExecutionException(
            f"Snowflake returned {_SHOW_ROW_CAP} rows — the SHOW result "
            f"is at its row cap and likely truncated: {query}",
        )


class SnowflakeStructureReader(SQLConnectorStructureReader[SnowflakeConnector]):
    """Reads structure metadata from Snowflake information_schema."""

    @property
    def active_database(self) -> str | None:
        creds = self._connector.connection_wrapper.credentials
        return creds.database_name if creds else None

    @property
    def _ddl_builder(self) -> SnowflakeSqlglotDDLBuilder:
        """The builder owning every catalog query this reader runs."""
        return SnowflakeSqlglotDDLBuilder()

    def build_full_object_path(
        self,
        schema: str | None,
        object_name: str,
    ) -> str:
        """Qualify with the database level of Snowflake's hierarchy.

        Lowercased throughout, like every name this reader returns,
        so keys built from config values and from catalog rows
        (uppercase) compare equal.
        """
        base = f"{schema}.{object_name}" if schema else object_name
        db = self.active_database
        return f"{db}.{base}".lower() if db else base.lower()

    def extract_structures(
        self,
        database: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
        **kwargs: Any,
    ) -> list[Structure]:
        db = database or self.active_database
        if db is None:
            return []

        # LIKE treats "_" as a single-char wildcard, so the rows are
        # re-filtered on the exact name below.
        query = self._ddl_builder.build_show_objects_query(
            database=db,
            schema=schema,
            object_pattern=object_name,
        )

        result = self._connector.execute_query(query)
        # A failed metadata read must raise, never degrade to "no
        # objects" — an empty result would make the deploy plan
        # CREATEs for every structure that actually exists.
        result.raise_on_error(f"Snowflake object listing failed: {query}")
        df = result.get_result_df()
        _guard_show_row_cap(df=df, query=query)

        structures: list[Structure] = []
        if df.empty:
            return structures
        for _, row in df.iterrows():
            if row["kind"] not in ("TABLE", "VIEW"):
                continue
            # A database-wide scope includes the read-only
            # INFORMATION_SCHEMA views; they are never deploy targets.
            if row["schema_name"].upper() == "INFORMATION_SCHEMA":
                continue
            table_name = row["name"]
            if object_name and table_name != object_name.upper():
                continue
            structure = self._read_table_structure(
                database=db,
                schema=row["schema_name"],
                table_name=table_name,
                structure_type="TABLE" if row["kind"] == "TABLE" else "VIEW",
            )
            structures.append(structure)

        return structures

    def extract_all_structures(
        self,
        schema: str | None = None,
    ) -> dict[str, Structure]:
        """Extract every table/view in the schema in one batch of round trips.

        Where ``extract_structures`` pays ``SHOW OBJECTS`` (with a
        per-table ``LIKE``) plus one ``INFORMATION_SCHEMA.COLUMNS``,
        one ``SHOW PRIMARY KEYS`` and one ``SHOW UNIQUE KEYS`` *per
        table*, this reads all four schema-wide — each query returns
        rows for every table in the schema, grouped by table name in
        Python since ``SHOW ... IN SCHEMA`` has no per-table scope.
        """
        db = self.active_database
        if db is None:
            return {}

        query = self._ddl_builder.build_show_objects_query(
            database=db,
            schema=schema,
        )
        result = self._connector.execute_query(query)
        result.raise_on_error(f"Snowflake object listing failed: {query}")
        objects_df = result.get_result_df()
        _guard_show_row_cap(df=objects_df, query=query)
        if objects_df.empty:
            return {}

        # A database-wide scope includes the read-only
        # INFORMATION_SCHEMA views; they are never deploy targets.
        table_rows = [
            row
            for _, row in objects_df.iterrows()
            if row["kind"] in ("TABLE", "VIEW")
            and row["schema_name"].upper() != "INFORMATION_SCHEMA"
        ]
        if not table_rows:
            return {}

        # Every returned object shares the same database; the schema
        # is read back per-row since a database-wide scope spans many
        # schemas, but the batched detail queries below are still
        # issued once per distinct schema actually present.
        schemas_in_scope = {row["schema_name"] for row in table_rows}

        all_columns: dict[tuple[str, str], list[dict[str, Any]]] = {}
        all_primary_keys: dict[tuple[str, str], tuple[str, list[str]]] = {}
        all_unique_keys: dict[tuple[str, str], dict[str, list[str]]] = {}
        for schema_name in schemas_in_scope:
            all_columns.update(
                self._get_all_columns(database=db, schema=schema_name),
            )
            all_primary_keys.update(
                self._get_all_primary_keys(database=db, schema=schema_name),
            )
            all_unique_keys.update(
                self._get_all_unique_keys(database=db, schema=schema_name),
            )

        structures: dict[str, Structure] = {}
        for row in table_rows:
            table_name = row["name"]
            table_schema = row["schema_name"]
            key = (table_schema, table_name)
            pk_constraint_name, pk_fields = all_primary_keys.get(key, (None, []))
            structure = self._build_structure(
                database=db,
                schema=table_schema,
                table_name=table_name,
                structure_type="TABLE" if row["kind"] == "TABLE" else "VIEW",
                columns=all_columns.get(key, []),
                pk_fields=pk_fields,
                unique_keys=all_unique_keys.get(key, {}),
                pk_constraint_name=pk_constraint_name,
            )
            full_path = self.build_full_object_path(
                schema=table_schema,
                object_name=structure.name,
            )
            structures[full_path] = structure
        return structures

    def get_all_dependent_views(
        self,
        schema: str,
    ) -> dict[str, list[str]]:
        """Return every direct view-dependency edge, parsed from definitions.

        Snowflake's OBJECT_DEPENDENCIES account-usage view lags by
        hours — useless right after DDL — so the edges are derived by
        parsing the definitions ``SHOW VIEWS`` returns.
        """
        db = self.active_database
        if db is None:
            return {}
        query = self._ddl_builder.build_show_views_query(
            database=db,
            schema=schema,
        )
        result = self._connector.execute_query(query)
        result.raise_on_error(f"Snowflake view listing failed: {query}")
        df = result.get_result_df()
        _guard_show_row_cap(df=df, query=query)
        if df.empty:
            return {}
        view_definitions = {
            str(row["name"]).lower(): str(row["text"])
            for _, row in df.iterrows()
            if row.get("text")
        }
        return parse_view_dependencies(
            view_definitions=view_definitions,
            dialect="snowflake",
        )

    def _read_table_structure(
        self,
        database: str,
        schema: str,
        table_name: str,
        structure_type: str,
    ) -> SnowflakeStructure:
        query = self._ddl_builder.build_table_columns_query(
            database=database,
            schema=schema,
            table_name=table_name,
        )
        result = self._connector.execute_query(query)
        result.raise_on_error(f"Snowflake column read failed: {query}")
        df = result.get_result_df()
        columns: list[dict[str, Any]] = (
            df.to_dict("records") if not df.empty else []  # type: ignore[assignment]
        )

        pk_constraint_name, pk_fields = self._read_primary_key(
            database,
            schema,
            table_name,
        )
        unique_keys = self._read_unique_keys(
            database=database,
            schema=schema,
            table_name=table_name,
        )
        return self._build_structure(
            database=database,
            schema=schema,
            table_name=table_name,
            structure_type=structure_type,
            columns=columns,
            pk_fields=pk_fields,
            unique_keys=unique_keys,
            pk_constraint_name=pk_constraint_name,
        )

    def _build_structure(
        self,
        database: str,
        schema: str,
        table_name: str,
        structure_type: str,
        columns: list[dict[str, Any]],
        pk_fields: list[str],
        unique_keys: dict[str, list[str]],
        pk_constraint_name: str | None = None,
    ) -> SnowflakeStructure:
        """Build a structure from pre-fetched column/key metadata.

        Shared by the per-table (``_read_table_structure``) and
        schema-wide (``extract_all_structures``) paths so both build
        byte-identical ``Structure`` objects for the same table.
        """
        fields: dict[str, Field] = {}
        for col in columns:
            col_name = col["column_name"].lower()
            data_type = col["data_type"]
            field = Field(
                name=col_name,
                data_type=data_type,
                default_value=normalize_column_default(
                    raw_default=col["column_default"],
                ),
            )
            if col["is_nullable"] == "NO":
                field.add_characterisation("mandatory")
            fields[col_name] = field

        structure = SnowflakeStructure(
            name=table_name.lower(),
            structure_type=structure_type,
            connector_type="snowflake",
            properties={
                "database": database,
                "schema": schema,
            },
            fields=fields,
        )

        if pk_fields:
            structure.add_characterisation(
                StructureCharacterisation(
                    characterisation=StructureCharacterisationDefinitionNames.PRIMARY_KEY,
                    name=pk_constraint_name or f"pk_{table_name.lower()}",
                    linked_fields=pk_fields,
                )
            )

        for constraint_name, constraint_columns in unique_keys.items():
            structure.add_characterisation(
                StructureCharacterisation(
                    characterisation=StructureCharacterisationDefinitionNames.UNIQUE,
                    name=constraint_name,
                    linked_fields=constraint_columns,
                )
            )

        return structure

    def _get_all_columns(
        self,
        database: str,
        schema: str,
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        """Read the columns of every table in the schema in one call."""
        query = self._ddl_builder.build_table_columns_query(
            database=database,
            schema=schema,
        )
        result = self._connector.execute_query(query)
        result.raise_on_error(f"Snowflake column read failed: {query}")
        df = result.get_result_df()
        columns_by_table: dict[tuple[str, str], list[dict[str, Any]]] = {}
        if df.empty:
            return columns_by_table
        rows: list[dict[str, Any]] = df.to_dict("records")  # type: ignore[assignment]
        for row in rows:
            key = (schema, row["table_name"])
            columns_by_table.setdefault(key, []).append(row)
        return columns_by_table

    def _get_all_primary_keys(
        self,
        database: str,
        schema: str,
    ) -> dict[tuple[str, str], tuple[str, list[str]]]:
        """Read the primary key of every table in the schema.

        ``SHOW PRIMARY KEYS IN SCHEMA`` returns one row per key column
        for every table in the schema — the grouping key (table name)
        moves from the query scope to this post-processing step. The
        real constraint name is preserved (lowercased), like the
        PostgreSQL reader does.
        """
        query = self._ddl_builder.build_show_primary_keys_query(
            database=database,
            schema=schema,
        )
        result = self._connector.execute_query(query)
        result.raise_on_error(f"Snowflake primary-key read failed: {query}")
        df = result.get_result_df()
        _guard_show_row_cap(df=df, query=query)
        pk_by_table: dict[tuple[str, str], tuple[str, list[str]]] = {}
        if df.empty:
            return pk_by_table
        df = df.sort_values("key_sequence")
        for _, row in df.iterrows():
            key = (schema, row["table_name"])
            constraint_name, columns = pk_by_table.setdefault(
                key,
                (row["constraint_name"].lower(), []),
            )
            columns.append(row["column_name"].lower())
        return pk_by_table

    def _get_all_unique_keys(
        self,
        database: str,
        schema: str,
    ) -> dict[tuple[str, str], dict[str, list[str]]]:
        """Read the unique constraints of every table in the schema.

        ``SHOW UNIQUE KEYS IN SCHEMA`` returns one row per key column
        for every table in the schema, grouped here by table name and
        then by constraint name.
        """
        query = self._ddl_builder.build_show_unique_keys_query(
            database=database,
            schema=schema,
        )
        result = self._connector.execute_query(query)
        result.raise_on_error(f"Snowflake unique-key read failed: {query}")
        df = result.get_result_df()
        _guard_show_row_cap(df=df, query=query)
        unique_by_table: dict[tuple[str, str], dict[str, list[str]]] = {}
        if df.empty:
            return unique_by_table
        for _, row in df.sort_values("key_sequence").iterrows():
            key = (schema, row["table_name"])
            constraint_name = row["constraint_name"].lower()
            unique_by_table.setdefault(key, {}).setdefault(
                constraint_name,
                [],
            ).append(row["column_name"].lower())
        return unique_by_table

    def _read_primary_key(
        self,
        database: str,
        schema: str,
        table_name: str,
    ) -> tuple[str | None, list[str]]:
        """Read the primary key via ``SHOW PRIMARY KEYS``.

        Snowflake's information_schema has no ``KEY_COLUMN_USAGE``
        view — ``SHOW PRIMARY KEYS`` is the supported way to list the
        key columns. The identifiers come from catalog rows, so they
        are the actual (uppercase) names and are quoted as-is. The
        real constraint name is preserved (lowercased).
        """
        query = self._ddl_builder.build_show_primary_keys_query(
            database=database,
            schema=schema,
            table_name=table_name,
        )
        result = self._connector.execute_query(query)
        result.raise_on_error(f"Snowflake primary-key read failed: {query}")
        df = result.get_result_df()
        if df.empty:
            return None, []
        df = df.sort_values("key_sequence")
        constraint_name = str(df.iloc[0]["constraint_name"]).lower()
        return constraint_name, [row["column_name"].lower() for _, row in df.iterrows()]

    def _read_unique_keys(
        self,
        database: str,
        schema: str,
        table_name: str,
    ) -> dict[str, list[str]]:
        """Read the unique constraints via ``SHOW UNIQUE KEYS``.

        Returns a mapping of constraint name (lowercased) to its
        ordered column names.
        """
        query = self._ddl_builder.build_show_unique_keys_query(
            database=database,
            schema=schema,
            table_name=table_name,
        )
        result = self._connector.execute_query(query)
        result.raise_on_error(f"Snowflake unique-key read failed: {query}")
        df = result.get_result_df()
        unique_keys: dict[str, list[str]] = {}
        if df.empty:
            return unique_keys
        for _, row in df.sort_values("key_sequence").iterrows():
            constraint_name = row["constraint_name"].lower()
            unique_keys.setdefault(constraint_name, []).append(
                row["column_name"].lower(),
            )
        return unique_keys
