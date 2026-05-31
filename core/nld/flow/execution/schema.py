import pyarrow as pa

from nld.engine.pyarrow import PyArrowPydanticStructureMapper
from nld.flow.execution.execution_info import (
    FlowExecutionInfo,
    FlowStepExecutionInfo,
)


def get_flow_step_execution_info_schema() -> pa.Schema:
    """
    Get the PyArrow schema for FlowStepExecutionInfo.

    Returns:
        PyArrow schema for flow step execution info.
    """
    return PyArrowPydanticStructureMapper.get_pyarrow_schema(FlowStepExecutionInfo)


def get_flow_execution_info_schema() -> pa.Schema:
    """
    Get the PyArrow schema for FlowExecutionInfo.

    The steps field is stored as JSON string since it contains nested objects.

    Returns:
        PyArrow schema for flow execution info.
    """
    return PyArrowPydanticStructureMapper.get_pyarrow_schema(FlowExecutionInfo)


def get_execution_state_schema() -> pa.Schema:
    """
    Get the PyArrow schema for FlowExecutionState.

    This is the same as FlowExecutionInfo schema since state contains
    a single execution info (last_processed).

    Returns:
        PyArrow schema for execution state.
    """
    return get_flow_execution_info_schema()


def get_execution_history_schema() -> pa.Schema:
    """
    Get the PyArrow schema for FlowExecutionHistory.

    This is the same as FlowExecutionInfo schema since history contains
    a list of execution info records.

    Returns:
        PyArrow schema for execution history.
    """
    return get_flow_execution_info_schema()
