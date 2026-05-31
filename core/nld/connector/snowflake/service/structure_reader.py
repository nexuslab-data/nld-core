from typing import Any

from nld.connector.base.structure_reader import SQLConnectorStructureReader
from nld.connector.snowflake.snowflake_connector import SnowflakeConnector
from nld.structure import Structure
from nld.structure.field.field import Field
from nld.structure.structure.structure_characterisation import (
    StructureCharacterisation,
)
from nld.structure.structure.structure_characterisation_def import (
    StructureCharacterisationDefinitionNames,
)


def _escape_sql_literal(value: str) -> str:
    """Escape a SQL string literal to prevent SQL injection."""
    return value.replace("'", "''")


class SnowflakeStructureReader(SQLConnectorStructureReader[SnowflakeConnector]):
    """Reads structure metadata from Snowflake information_schema."""

    @property
    def active_database(self) -> str | None:
        creds = self._connector.connection_wrapper.credentials
        return creds.database_name if creds else None

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

        query = (
            "SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE "
            "FROM INFORMATION_SCHEMA.TABLES "
            f"WHERE TABLE_CATALOG = '{_escape_sql_literal(db)}'"
        )
        if schema:
            query += f" AND TABLE_SCHEMA = '{_escape_sql_literal(schema)}'"
        if object_name:
            query += f" AND TABLE_NAME = '{_escape_sql_literal(object_name)}'"

        result = self._connector.execute_query(query)
        df = result.get_output_data_as_df()

        structures: list[Structure] = []
        for _, row in df.iterrows():
            row_schema = row["table_schema"]
            table_name = row["table_name"]
            table_type = "TABLE" if row["table_type"] == "BASE TABLE" else "VIEW"
            structure = self._read_table_structure(
                database=db,
                schema=row_schema,
                table_name=table_name,
                structure_type=table_type,
            )
            structures.append(structure)

        return structures

    def _read_table_structure(
        self,
        database: str,
        schema: str,
        table_name: str,
        structure_type: str,
    ) -> Structure:
        query = (
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, "
            "CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_CATALOG = '{_escape_sql_literal(database)}' "
            f"AND TABLE_SCHEMA = '{_escape_sql_literal(schema)}' "
            f"AND TABLE_NAME = '{_escape_sql_literal(table_name)}' "
            "ORDER BY ORDINAL_POSITION"
        )
        result = self._connector.execute_query(query)
        df = result.get_output_data_as_df()

        fields: dict[str, Field] = {}
        for _, row in df.iterrows():
            col_name = row["column_name"].lower()
            data_type = row["data_type"]
            field = Field(name=col_name, data_type=data_type)
            if row["is_nullable"] == "NO":
                field.add_characterisation("mandatory")
            fields[col_name] = field

        structure = Structure(
            name=table_name.lower(),
            structure_type=structure_type,
            fields=fields,
        )

        pk_fields = self._read_primary_key(database, schema, table_name)
        if pk_fields:
            structure.add_characterisation(
                StructureCharacterisation(
                    characterisation=StructureCharacterisationDefinitionNames.PRIMARY_KEY,
                    name=f"pk_{table_name.lower()}",
                    linked_fields=pk_fields,
                )
            )

        return structure

    def _read_primary_key(
        self,
        database: str,
        schema: str,
        table_name: str,
    ) -> list[str]:
        query = (
            "SELECT KCU.COLUMN_NAME "
            "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS TC "
            "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE KCU "
            "  ON TC.TABLE_CATALOG = KCU.TABLE_CATALOG "
            "  AND TC.CONSTRAINT_NAME = KCU.CONSTRAINT_NAME "
            "  AND TC.TABLE_SCHEMA = KCU.TABLE_SCHEMA "
            "  AND TC.TABLE_NAME = KCU.TABLE_NAME "
            f"WHERE TC.TABLE_CATALOG = '{_escape_sql_literal(database)}' "
            f"AND TC.TABLE_SCHEMA = '{_escape_sql_literal(schema)}' "
            f"AND TC.TABLE_NAME = '{_escape_sql_literal(table_name)}' "
            "AND TC.CONSTRAINT_TYPE = 'PRIMARY KEY' "
            "ORDER BY KCU.ORDINAL_POSITION"
        )
        result = self._connector.execute_query(query)
        df = result.get_output_data_as_df()
        return [row["column_name"].lower() for _, row in df.iterrows()]
