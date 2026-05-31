import re
from typing import TYPE_CHECKING

import pyarrow as pa

if TYPE_CHECKING:
    from nld.structure import Structure

# Canonical string representations for PyArrow types
# Used to avoid string roundtrip issues with str(pa.DataType)
PYARROW_TYPE_STRINGS = {
    pa.int64(): "int64",
    pa.int32(): "int32",
    pa.float64(): "float64",
    pa.float32(): "float32",
    pa.bool_(): "bool",
    pa.string(): "string",
    pa.date32(): "date32",
}


def get_canonical_type_string(pa_type: pa.DataType) -> str:
    """Get a canonical string representation for a PyArrow type.

    Args:
        pa_type: PyArrow data type

    Returns:
        Canonical string representation of the type
    """
    if pa_type in PYARROW_TYPE_STRINGS:
        return PYARROW_TYPE_STRINGS[pa_type]
    # Handle timestamp with timezone
    if pa.types.is_timestamp(pa_type):
        if pa_type.tz:
            return f"timestamp[{pa_type.unit}, tz={pa_type.tz.lower()}]"
        return f"timestamp[{pa_type.unit}]"
    return str(pa_type).lower()


def convert_structure_to_pyarrow_schema(structure: "Structure") -> pa.Schema:
    """
    Convert a Structure to a PyArrow schema.

    Maps structure fields to PyArrow data types based on the field's data_type
    attribute. Uses the field's mandatory characterisation to determine nullable.

    Args:
        structure: Structure object containing field definitions

    Returns:
        PyArrow schema with correct nullable settings

    Example:
        >>> from nld.structure import Structure
        >>> from nld.structure.field import Field
        >>> structure = Structure(
        ...     name="test",
        ...     structure_type="TABLE",
        ...     fields={"id": Field(name="id", data_type="int64")}
        ... )
        >>> schema = convert_structure_to_pyarrow_schema(structure)
    """
    fields = []
    for field_name, field in structure.fields.items():
        pa_type = _map_data_type_string_to_pyarrow(field.data_type)
        # mandatory = NOT NULL = not nullable
        is_nullable = not field.is_mandatory()
        fields.append(pa.field(field_name, pa_type, nullable=is_nullable))
    return pa.schema(fields)


def _map_data_type_string_to_pyarrow(data_type: str) -> pa.DataType:
    """
    Map a data type string to a PyArrow data type.

    Args:
        data_type: String representation of the data type

    Returns:
        PyArrow data type
    """
    data_type_lower = data_type.lower().strip()

    # Integer types
    if data_type_lower in ("int64", "bigint", "integer", "int"):
        return pa.int64()
    elif data_type_lower in ("int32",):
        return pa.int32()

    # Float types
    elif data_type_lower in ("float64", "double", "double precision", "float"):
        return pa.float64()
    elif data_type_lower in ("float32",):
        return pa.float32()

    # Boolean
    elif data_type_lower in ("bool", "boolean", "bool_"):
        return pa.bool_()

    # String types
    elif data_type_lower in ("string", "text", "varchar", "str"):
        return pa.string()

    # Timestamp types - handle various formats
    elif data_type_lower.startswith("timestamp"):
        return _parse_timestamp_type(data_type_lower)

    # Date types
    elif data_type_lower in ("date", "date32"):
        return pa.date32()

    # JSON/complex types
    elif data_type_lower in ("json", "jsonb"):
        return pa.string()

    # UUID
    elif data_type_lower in ("uuid",):
        return pa.string()

    # Default to string
    else:
        return pa.string()


def _parse_timestamp_type(data_type_lower: str) -> pa.DataType:
    """
    Parse timestamp type strings into PyArrow timestamp types.

    Handles various formats:
    - "timestamp" -> timestamp[us, tz=UTC]
    - "timestamp[us]" -> timestamp[us]
    - "timestamp[us, tz=utc]" -> timestamp[us, tz=UTC]
    - "timestamp[us, tz=UTC]" -> timestamp[us, tz=UTC]

    Args:
        data_type_lower: Lowercase timestamp type string

    Returns:
        PyArrow timestamp type
    """
    # Simple timestamp without parameters
    if data_type_lower == "timestamp":
        return pa.timestamp("us", tz="UTC")

    # Parse timestamp with parameters: timestamp[unit] or timestamp[unit, tz=timezone]
    match = re.match(r"timestamp\[(\w+)(?:,\s*tz=(\w+))?\]", data_type_lower)
    if match:
        unit = match.group(1)
        tz = match.group(2)
        if tz:
            # Normalize timezone to uppercase for UTC
            tz_normalized = "UTC" if tz.lower() == "utc" else tz
            return pa.timestamp(unit, tz=tz_normalized)
        return pa.timestamp(unit)

    # Default to timestamp with UTC
    return pa.timestamp("us", tz="UTC")
