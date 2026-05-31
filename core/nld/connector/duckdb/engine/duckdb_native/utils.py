from typing import Any

from nld.connector.duckdb.duckdb_data_type import DuckDBDataTypes
from nld.structure import Field, Structure


class DuckDBUtil:
    """Utility class for DuckDB operations.

    This class provides methods to handle DuckDB-specific data types
    and result metadata.
    """

    @classmethod
    def get_duckdb_data_type_mapping(cls) -> dict[str, str]:
        """Get a mapping of DuckDB type names to canonical types.

        Returns:
            A dictionary mapping DuckDB type name strings to
            DuckDBDataTypes constants.
        """
        return {
            "BIGINT": DuckDBDataTypes.BIGINT,
            "BIT": DuckDBDataTypes.BIT,
            "BLOB": DuckDBDataTypes.BLOB,
            "BOOLEAN": DuckDBDataTypes.BOOLEAN,
            "DATE": DuckDBDataTypes.DATE,
            "DECIMAL": DuckDBDataTypes.DECIMAL,
            "DOUBLE": DuckDBDataTypes.DOUBLE,
            "FLOAT": DuckDBDataTypes.FLOAT,
            "HUGEINT": DuckDBDataTypes.HUGEINT,
            "INTEGER": DuckDBDataTypes.INTEGER,
            "INT": DuckDBDataTypes.INTEGER,
            "INTERVAL": DuckDBDataTypes.INTERVAL,
            "JSON": DuckDBDataTypes.JSON,
            "SMALLINT": DuckDBDataTypes.SMALLINT,
            "TEXT": DuckDBDataTypes.TEXT,
            "TIME": DuckDBDataTypes.TIME,
            "TIMESTAMP": DuckDBDataTypes.TIMESTAMP,
            "TIMESTAMP WITH TIME ZONE": DuckDBDataTypes.TIMESTAMPTZ,
            "TIMESTAMPTZ": DuckDBDataTypes.TIMESTAMPTZ,
            "TINYINT": DuckDBDataTypes.TINYINT,
            "UBIGINT": DuckDBDataTypes.UBIGINT,
            "UHUGEINT": DuckDBDataTypes.UHUGEINT,
            "UINTEGER": DuckDBDataTypes.UINTEGER,
            "USMALLINT": DuckDBDataTypes.USMALLINT,
            "UTINYINT": DuckDBDataTypes.UTINYINT,
            "UUID": DuckDBDataTypes.UUID,
            "VARCHAR": DuckDBDataTypes.VARCHAR,
            "CHARACTER VARYING": DuckDBDataTypes.CHARACTER_VARYING,
        }

    @classmethod
    def get_field_from_result_metadata(
        cls, result_metadata: list[Any]
    ) -> list[dict[str, str]]:
        """Get field information from the DuckDB result description.

        Args:
            result_metadata: The cursor.description from DuckDB.

        Returns:
            A list of dictionaries with field name and type.
        """
        type_mapping = cls.get_duckdb_data_type_mapping()
        fields = []
        if result_metadata:
            for column in result_metadata:
                col_name = column[0]
                col_type = column[1] if len(column) > 1 else None
                # Use DuckDBPyType.id for the base type name
                # (e.g. "decimal" for DECIMAL(10,2)) to avoid
                # string parsing of parameterized types.
                if col_type is not None and hasattr(col_type, "id"):
                    col_type_key = str(col_type.id).upper()
                else:
                    col_type_key = str(col_type).upper() if col_type else "VARCHAR"
                data_type = type_mapping.get(col_type_key, DuckDBDataTypes.VARCHAR)
                fields.append(
                    {
                        "name": col_name,
                        "type": data_type,
                    }
                )
        return fields

    @classmethod
    def get_structure_from_metadata(
        cls, result_metadata: Any, row_count: int
    ) -> Structure:
        """Build a Structure from DuckDB cursor description."""
        structure = Structure(
            name="ResultSet",
            description=None,
            structure_type="PyDataSet",
            stats={"row_count": row_count},
        )
        field_dicts = cls.get_field_from_result_metadata(result_metadata)

        for field in field_dicts:
            structure.add_field(
                new_field=Field(
                    name=field["name"],
                    data_type=field["type"],
                ),
            )
        return structure
