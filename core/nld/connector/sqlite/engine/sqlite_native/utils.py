from typing import Any

from nld.connector.sqlite.connector_definition import (
    SQLiteDataTypes,
    resolve_storage_affinity,
)
from nld.structure import Field, Structure

# sqlite3 reports no column type on a cursor description, so the value's
# Python type is what a result-set structure can be built from.
_PYTHON_TYPE_TO_DATA_TYPE: dict[type, str] = {
    bool: SQLiteDataTypes.BOOLEAN,
    bytes: SQLiteDataTypes.BLOB,
    float: SQLiteDataTypes.REAL,
    int: SQLiteDataTypes.INTEGER,
    str: SQLiteDataTypes.TEXT,
}


class SQLiteUtil:
    """Utility class for SQLite operations."""

    @classmethod
    def get_storage_affinity(cls, data_type: str) -> str:
        """Resolve a declared type name to its SQLite storage affinity."""
        return resolve_storage_affinity(data_type)

    @classmethod
    def get_field_from_result_metadata(
        cls,
        result_metadata: list[Any] | None,
        first_row: tuple[Any, ...] | None = None,
    ) -> list[dict[str, str]]:
        """Get field information from a sqlite3 cursor description.

        The driver fills only the column name in ``cursor.description``, so
        the type is inferred from the first returned row when there is one
        and defaults to TEXT otherwise.
        """
        if not result_metadata:
            return []
        fields: list[dict[str, str]] = []
        for index, column in enumerate(result_metadata):
            value = (
                first_row[index]
                if first_row is not None and index < len(first_row)
                else None
            )
            data_type = _PYTHON_TYPE_TO_DATA_TYPE.get(
                type(value),
                SQLiteDataTypes.TEXT,
            )
            fields.append(
                {
                    "name": column[0],
                    "type": data_type,
                }
            )
        return fields

    @classmethod
    def get_structure_from_metadata(
        cls,
        result_metadata: Any,
        row_count: int,
        first_row: tuple[Any, ...] | None = None,
    ) -> Structure:
        """Build a Structure from a sqlite3 cursor description."""
        structure = Structure(
            name="ResultSet",
            description=None,
            structure_type="PyDataSet",
            stats={"row_count": row_count},
        )
        for field in cls.get_field_from_result_metadata(
            result_metadata=result_metadata,
            first_row=first_row,
        ):
            structure.add_field(
                new_field=Field(
                    name=field["name"],
                    data_type=field["type"],
                ),
            )
        return structure
