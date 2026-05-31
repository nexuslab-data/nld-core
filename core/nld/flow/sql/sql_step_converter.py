from decimal import Decimal
from typing import Any

from nld.connector.base.query import (
    QueryExecResult,
    QueryExecResultStatus,
    SQLOperationType,
)
from nld.flow.execution.execution_info import FlowStepExecutionInfo
from nld.flow.utils import FlowStepExecStatus

_OPERATION_TO_TARGET_ENTRY_FIELD: dict[SQLOperationType, str] = {
    SQLOperationType.COPY: "target_entries_inserted_in_success",
    SQLOperationType.DELETE: "target_entries_deleted_in_success",
    SQLOperationType.INSERT: "target_entries_inserted_in_success",
    SQLOperationType.MERGE: "target_entries_inserted_in_success",
    SQLOperationType.UPDATE: "target_entries_updated_in_success",
}


def _build_step_name(
    strategy_name: str,
    query_result: QueryExecResult,
) -> str:
    """Build a human-readable step name from strategy, operation, and target."""
    parts = [strategy_name]

    if strategy_name != "VIEW" and query_result.operation_type is not None:
        parts.append(query_result.operation_type.value)

    if query_result.query_name:
        parts.append(query_result.query_name)

    return " - ".join(parts)


def convert_query_result_to_step(
    query_result: QueryExecResult,
    flow_uid: str,
    strategy_name: str,
    step_category: str | None = None,
) -> FlowStepExecutionInfo:
    """Convert a QueryExecResult into a FlowStepExecutionInfo.

    Maps connector query output to step tracking with lifecycle,
    status, error info, and metadata including row_count, query_id,
    and operation_type.
    """
    duration = (query_result.end_tst - query_result.start_tst).total_seconds()
    duration_seconds = Decimal(str(duration)).quantize(Decimal("0.1"))

    is_success = query_result.exec_status == QueryExecResultStatus.SUCCESS
    step_status = (
        FlowStepExecStatus.SUCCEEDED if is_success else FlowStepExecStatus.FAILED
    )
    step_error = None if is_success else query_result.get_error_message()

    metadata: dict[str, object] = {}
    if query_result.operation_type is not None:
        metadata["operation_type"] = query_result.operation_type.value
    if query_result.query_id is not None:
        metadata["query_id"] = query_result.query_id
    if query_result.row_count is not None:
        metadata["row_count"] = query_result.row_count

    target_entry_kwargs: dict[str, Any] = {}
    operation_type = query_result.operation_type
    if is_success and query_result.row_count is not None and operation_type is not None:
        target_field = _OPERATION_TO_TARGET_ENTRY_FIELD.get(operation_type)
        if target_field is not None:
            target_entry_kwargs[target_field] = query_result.row_count

    return FlowStepExecutionInfo(
        flow_uid=flow_uid,
        step_name=_build_step_name(
            strategy_name=strategy_name,
            query_result=query_result,
        ),
        step_category=step_category,
        started_at=query_result.start_tst,
        ended_at=query_result.end_tst,
        duration_seconds=duration_seconds,
        query=query_result.query,
        step_status=step_status,
        step_error=step_error,
        metadata=metadata,
        **target_entry_kwargs,
    )
