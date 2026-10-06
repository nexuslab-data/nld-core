from __future__ import annotations

import re
from typing import Any

from nld.connector.base import SQLConnectorStructureReader
from nld.connector.base.structure_reader import parse_view_dependencies
from nld.connector.sqlite.constants import SQLITE_DIALECT, SQLITE_SCHEMA
from nld.connector.sqlite.engine.sqlite_native.connector import SQLiteSQLConnector
from nld.connector.sqlite.sqlglot.ddl import SQLiteSqlglotDDLBuilder
from nld.connector.sqlite.sqlite_structure import SQLiteStructure
from nld.structure import (
    Field,
    FieldCharacterisationDefinitionNames,
    Structure,
    StructureCharacterisation,
    StructureCharacterisationDefinitionNames,
)
from nld.structure.field.field_data_type import FieldDataType

# pragma_index_list origins: 'c' is a declared CREATE INDEX, 'u' an index
# SQLite created for an inline UNIQUE, 'pk' the one backing the primary key.
INDEX_ORIGIN_CREATE_INDEX = "c"
INDEX_ORIGIN_PRIMARY_KEY = "pk"
INDEX_ORIGIN_UNIQUE_CONSTRAINT = "u"

# The DDL renders a scaled type as "NUMERIC(12, 2)"; the compact form the
# field parser reads carries no space, so the separator is normalised first.
_TYPE_ARGUMENT_SEPARATOR_PATTERN = re.compile(r"\s*,\s*")


class SQLiteStructureReader(SQLConnectorStructureReader[SQLiteSQLConnector]):
    """Service to extract database structure from SQLite.

    Reads ``sqlite_master`` and the ``pragma_*`` table-valued functions,
    SQLite having no ``information_schema``. The declared column type comes
    back verbatim from ``pragma_table_info``, so the read-back type matches
    the DDL that created it exactly and a second deploy is a no-op.
    """

    @property
    def active_database(self) -> str | None:
        """Get the database file backing the connection."""
        return self._connector.get_active_database()

    @property
    def _ddl_builder(self) -> SQLiteSqlglotDDLBuilder:
        """The builder owning every catalogue query this reader runs."""
        return SQLiteSqlglotDDLBuilder()

    def extract_structures(
        self,
        database: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
        **kwargs: Any,
    ) -> list[Structure]:
        """Extract structures (tables/views) from SQLite.

        Args:
            database: Ignored. SQLite reads the file the connection opened.
            schema: The schema name echoed back on the structures. SQLite
                has a single namespace, so this selects nothing; it is
                carried so the deploy finds the structures under the schema
                it asked for.
            object_name: Optional table/view name to filter by.

        Returns:
            List of Structure objects representing tables and views.
        """
        tables = self._get_tables_and_views(object_name=object_name)
        if not tables:
            return []

        all_columns = self._get_all_columns(object_name=object_name)
        all_indexes = self._get_all_indexes(object_name=object_name)

        structures: list[Structure] = []
        for table_info in tables:
            table_name = table_info["table_name"]
            structures.append(
                self._build_structure(
                    table_info=table_info,
                    columns=all_columns.get(table_name, []),
                    indexes=all_indexes.get(table_name, {}),
                    schema=schema or SQLITE_SCHEMA,
                )
            )
        return structures

    def get_all_dependent_views(
        self,
        schema: str,
    ) -> dict[str, list[str]]:
        """Return every direct view-dependency edge, parsed from definitions.

        SQLite has no dependency catalogue, so the edges come from parsing
        the definitions ``sqlite_master`` stores.
        """
        result = self._connector.execute_query(self._ddl_builder.build_views_query())
        result.raise_on_error("SQLite view listing failed")
        view_definitions = {
            str(record["view_name"]).lower(): str(record["sql"])
            for record in result.get_result_records()
            if record.get("sql")
        }
        if not view_definitions:
            return {}
        return parse_view_dependencies(
            view_definitions=view_definitions,
            dialect=SQLITE_DIALECT,
        )

    def get_dependent_views(
        self,
        schema: str,
        object_name: str,
    ) -> list[str]:
        """Return the views directly depending on an object."""
        return self.get_all_dependent_views(schema=schema).get(
            object_name.lower(),
            [],
        )

    def _get_tables_and_views(
        self,
        object_name: str | None,
    ) -> list[dict[str, Any]]:
        """Retrieve the list of tables and views."""
        result = self._connector.execute_query(
            self._ddl_builder.build_tables_and_views_query(object_name=object_name),
        )
        return result.get_result_records()

    def _get_all_columns(
        self,
        object_name: str | None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Retrieve columns for all filtered objects at once."""
        result = self._connector.execute_query(
            self._ddl_builder.build_table_columns_query(object_name=object_name),
        )
        columns_by_table: dict[str, list[dict[str, Any]]] = {}
        for record in result.get_result_records():
            columns_by_table.setdefault(record["table_name"], []).append(record)
        return columns_by_table

    def _get_all_indexes(
        self,
        object_name: str | None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Retrieve indexes for all filtered objects, keyed by index name."""
        result = self._connector.execute_query(
            self._ddl_builder.build_index_columns_query(object_name=object_name),
        )
        indexes_by_table: dict[str, dict[str, dict[str, Any]]] = {}
        for record in result.get_result_records():
            table_indexes = indexes_by_table.setdefault(record["table_name"], {})
            index = table_indexes.setdefault(
                record["index_name"],
                {
                    "is_unique": bool(record["is_unique"]),
                    "origin": record["index_origin"],
                    "columns": [],
                },
            )
            index["columns"].append(record["column_name"])
        return indexes_by_table

    def _build_structure(
        self,
        table_info: dict[str, Any],
        columns: list[dict[str, Any]],
        indexes: dict[str, dict[str, Any]],
        schema: str,
    ) -> SQLiteStructure:
        """Build a Structure object from extracted metadata."""
        table_name = table_info["table_name"]

        fields: dict[str, Field] = {}
        primary_key_columns: list[tuple[int, str]] = []
        for column in columns:
            field = self._build_field(column_info=column)
            fields[field.name] = field
            primary_key_position = int(column.get("primary_key_position") or 0)
            if primary_key_position > 0:
                primary_key_columns.append((primary_key_position, field.name))

        characterisations: list[StructureCharacterisation] = []

        if primary_key_columns:
            # SQLite does not report the constraint name a CREATE TABLE
            # declared, so the key is named canonically instead: the diff
            # engine then sees the same name on every read cycle.
            characterisations.append(
                StructureCharacterisation(
                    name=f"pk_{table_name.lower()}",
                    characterisation=(
                        StructureCharacterisationDefinitionNames.PRIMARY_KEY
                    ),
                    linked_fields=[
                        column_name for _, column_name in sorted(primary_key_columns)
                    ],
                )
            )

        for index_name, index in indexes.items():
            # The index backing the primary key is already materialised as
            # the primary key characterisation; reporting it again would
            # make the diff engine drop and recreate it forever.
            if index["origin"] == INDEX_ORIGIN_PRIMARY_KEY:
                continue
            characterisation_type = (
                StructureCharacterisationDefinitionNames.UNIQUE
                if index["is_unique"]
                else StructureCharacterisationDefinitionNames.INDEX
            )
            characterisations.append(
                StructureCharacterisation(
                    name=index_name,
                    characterisation=characterisation_type,
                    linked_fields=index["columns"],
                )
            )

        return SQLiteStructure(
            name=table_name,
            structure_type=table_info["table_type"],
            connector_type="sqlite",
            properties={
                "database": self.active_database or "",
                "schema": schema,
            },
            fields=fields,
            characterisations=characterisations,
        )

    def _build_field(self, column_info: dict[str, Any]) -> Field:
        """Build a Field object from column metadata.

        ``pragma_table_info`` returns the type exactly as declared, so the
        compact form is parsed back into type, length and precision instead
        of being mapped through an engine type catalogue.
        """
        declared_type = _TYPE_ARGUMENT_SEPARATOR_PATTERN.sub(
            ",",
            str(column_info["data_type"] or "").strip(),
        )
        parsed_type = FieldDataType.from_string(declared_type)
        field = Field(
            name=column_info["column_name"],
            data_type=parsed_type.data_type.upper(),
            length=parsed_type.length,
            precision=parsed_type.precision,
            default_value=self._normalize_default(column_info.get("column_default")),
        )
        is_primary_key = int(column_info.get("primary_key_position") or 0) > 0
        if int(column_info.get("not_null") or 0) == 1 or is_primary_key:
            field.add_characterisation(FieldCharacterisationDefinitionNames.MANDATORY)
        return field

    @staticmethod
    def _normalize_default(raw_default: Any) -> str | None:
        """Normalize a read-back column default for comparison.

        SQLite stores the default expression verbatim, string literals
        included: the surrounding quotes are stripped so the value compares
        equal to the unquoted one a structure declares.
        """
        if raw_default is None:
            return None
        default = str(raw_default).strip()
        if len(default) >= 2 and default[0] == "'" and default[-1] == "'":
            return default[1:-1].replace("''", "'")
        return default
