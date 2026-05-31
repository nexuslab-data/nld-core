import pyarrow as pa

from nld.engine.pyarrow import PyArrowPydanticStructureMapper
from nld.flow.incremental.backend.plan import BackendStatePlanRow


def get_state_plans_index_schema() -> pa.Schema:
    """PyArrow schema for the consolidated state-plans index parquet file.

    The schema is derived from ``BackendStatePlanRow`` so it stays in lockstep
    with the Pydantic model the rest of the lifecycle code already uses.
    """
    return PyArrowPydanticStructureMapper.get_pyarrow_schema(BackendStatePlanRow)
