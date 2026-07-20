from typing import Any, Final

from nld.connector.postgresql.connector_definition import (
    PostgreSQLDataTypes,
)
from nld.structure import Field, Structure
from psycopg2 import Error as Psycopg2Error

POSTGRESQL_MAX_TEXT_LENGTH: Final[int] = 10485760


class Psycopg2SQLUtil:
    """Utility class for PostgreSQL operations.
    This class provides methods to handle PostgreSQL-specific data types,
    error messages, and result metadata.
    """

    @classmethod
    def get_standard_error_message(cls, error: Psycopg2Error) -> str:
        """Get a standard error message from a Psycopg2Error.
        Args:
            error (Psycopg2Error): The Psycopg2Error to extract the message from.
        Returns:
            str: A formatted error message containing the error code and message.
        """
        return f"Error {error.pgcode}: {error.pgerror}"

    @classmethod
    def get_postgresql_data_type_mapping(cls) -> dict[int, str]:
        """Get a mapping of PostgreSQL data types to their corresponding constants.
        This mapping is used to convert PostgreSQL data types to the
        PostgreSQLDataTypes enum.
        Returns:
            Dict[int, str]: A dictionary mapping PostgreSQL data type codes to
            PostgreSQLDataTypes constants.
        """
        return {
            23: PostgreSQLDataTypes.INTEGER,
            20: PostgreSQLDataTypes.BIGINT,
            21: PostgreSQLDataTypes.SMALLINT,
            25: PostgreSQLDataTypes.TEXT,
            1043: PostgreSQLDataTypes.CHARACTER_VARYING,
            16: PostgreSQLDataTypes.BOOL,
            1114: PostgreSQLDataTypes.TIMESTAMP,
            1184: PostgreSQLDataTypes.TIMESTAMPTZ,
            1082: PostgreSQLDataTypes.DATE,
            1700: PostgreSQLDataTypes.NUMERIC,
            700: PostgreSQLDataTypes.REAL,
            701: PostgreSQLDataTypes.DOUBLE_PRECISION,
            114: PostgreSQLDataTypes.JSON,
            17: PostgreSQLDataTypes.BYTEA,
        }

    @classmethod
    def get_field_from_result_metadata(
        cls, result_metadata: Any
    ) -> list[dict[str, str]]:
        """Get field information from the result metadata.
        Args:
            result_metadata (Any): The result metadata containing information about
            the columns in the result set.
        Returns:
            List[dict]: A list of dictionaries containing field information, including
            the name and data type of each column.
        """
        type_mapping = cls.get_postgresql_data_type_mapping()
        fields = []
        if result_metadata:
            for column in result_metadata:
                data_type = type_mapping.get(column.type_code, PostgreSQLDataTypes.TEXT)
                fields.append(
                    {
                        "name": column.name,
                        "type": data_type,
                    }
                )
        return fields

    @classmethod
    def get_structure_for_error_result(cls) -> Structure:
        """Get a structure for error results.
        This structure is used to represent the result of a query execution
        that encountered an error.
        Returns:
            Structure: A Structure object representing the error result.
        """
        structure = Structure(
            name="ResultSet",
            description=None,
            structure_type="PyDataSet",
            stats={"row_count": 0},
        )
        structure.add_field(
            new_field=Field(
                name="Error Message",
                data_type="text",
                length=POSTGRESQL_MAX_TEXT_LENGTH,
            ),
        )
        return structure

    @classmethod
    def get_structure_from_metadata(
        cls, result_metadata: Any, row_count: int
    ) -> Structure:
        """ """
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
                    length=POSTGRESQL_MAX_TEXT_LENGTH,
                ),
            )
        return structure
