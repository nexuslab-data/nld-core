# Import from the leaf module rather than the execution package root:
# the package root pulls the execution managers, which import the flow
# definition, which imports this quality package — a circular chain.
from nld.flow.execution.execution_info import FlowStepExecutionInfo
from nld.flow.quality.models.result import DataQualityCheckResult
from nld.flow.utils import FlowStepCategory
from nld.utils.datetime_util import get_current_datetime

DATA_QUALITY_FAILURE_STEP_NAME = "Data Quality - Measurement"


def convert_data_quality_check_result_to_step(
    result: DataQualityCheckResult,
    flow_uid: str,
) -> FlowStepExecutionInfo:
    """Convert one evaluated check result into an execution step.

    The step carries the full result payload in its metadata and maps the
    check outcome onto the step status: a valid status → SUCCEEDED, an
    outcome held at warning level → WARNING, and a failing one → FAILED.
    The result combines its status and declared severity into those two
    booleans, so the mapping stays a plain dispatch here. Keeping the
    conversion here keeps the step model out of the flow task's data
    quality code, mirroring the SQL step converter.
    """
    step_info = FlowStepExecutionInfo(
        flow_uid=flow_uid,
        step_name=result.get_step_name(),
        step_category=FlowStepCategory.DATA_QUALITY,
        started_at=get_current_datetime(),
        metadata=result.to_step_metadata(),
    )
    if result.is_step_failure:
        step_info.update_execution_status_to_failed(
            error_message=result.message or "Data quality check failed",
        )
    else:
        step_info.update_execution_status_to_completed(
            with_warning=not result.is_valid,
        )
    return step_info


def build_data_quality_failure_step(
    flow_uid: str,
    error_message: str,
) -> FlowStepExecutionInfo:
    """Build the FAILED step recording a measurement failure.

    Used when the checks could not be evaluated at all (broken query,
    unreachable target), so the failure stays visible in the step history
    without any check result to convert.
    """
    step_info = FlowStepExecutionInfo(
        flow_uid=flow_uid,
        step_name=DATA_QUALITY_FAILURE_STEP_NAME,
        step_category=FlowStepCategory.DATA_QUALITY,
        started_at=get_current_datetime(),
    )
    step_info.update_execution_status_to_failed(
        error_message=error_message,
    )
    return step_info
