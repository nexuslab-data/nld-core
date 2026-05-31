import pyarrow as pa

from nld.engine.pyarrow import PyArrowPydanticStructureMapper
from nld.flow.incremental.impl.by_key.state import (
    ByKeySingleKeyProcessingState,
    ByKeySingleKeyState,
)


def get_by_key_state_schema() -> pa.Schema:
    """
    Get the PyArrow schema for BY_KEY state Parquet files.

    This schema matches the ByKeySingleKeyState model fields.
    The parameters field is stored as JSON string.

    Returns:
        PyArrow schema for BY_KEY state.
    """
    return PyArrowPydanticStructureMapper.get_pyarrow_schema(ByKeySingleKeyState)


def get_by_key_processing_state_schema() -> pa.Schema:
    """
    Get the PyArrow schema for BY_KEY processing state Parquet files.

    This schema matches the ByKeySingleKeyProcessingState model fields.
    The parameters field is stored as JSON string.

    Returns:
        PyArrow schema for BY_KEY processing state.
    """
    return PyArrowPydanticStructureMapper.get_pyarrow_schema(
        ByKeySingleKeyProcessingState
    )
