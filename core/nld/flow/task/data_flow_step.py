import abc

from nld.flow.execution import FlowStepExecutionInfo
from nld.task.base.base_step import BaseStep
from nld.utils.datetime_util import get_current_datetime


class DataFlowStep(BaseStep, abc.ABC):
    """
    Data Flow Step.

    The steps should be called inside a data flow task.
    """

    init_params = ["flow_uid", "step_name"]
    run_params = []

    def __init__(self, flow_uid: str, step_name: str):
        super().__init__()
        self.step_execution_info = FlowStepExecutionInfo(
            flow_uid=flow_uid,
            step_name=step_name,
            started_at=get_current_datetime(),
        )

    @abc.abstractmethod
    def run_main(self) -> None:
        """
        Execute the main step logic.

        This method must be implemented by subclasses to define the specific flow logic.

        This method should also update the step_execution_info attribute with metadata
        on source and target loading.
        """
        raise NotImplementedError(
            "The method 'run_main' should be implemented in sub class."
        )

    def run(self) -> FlowStepExecutionInfo:  # type: ignore[override]
        """
        Execute the complete step logic and returns the flow execution information.
        """
        self.run_main()
        return self.step_execution_info
