import abc
from typing import Any

from nld.task.base.base_task import BaseTask
from nld.task.context import NldExecutionContext
from nld.task.execution import ExecutionInfo
from nld.utils.string_utils import split_camel_case_string


class StandardTask(BaseTask, metaclass=abc.ABCMeta):
    """Standard Task."""

    init_params = []
    run_params = []

    def __init__(self, **kwargs: Any) -> None:
        self.execution_context = NldExecutionContext.require_current()

        super().__init__(exec_uuid=self.execution_info.uuid)

    @property
    def execution_info(self) -> ExecutionInfo:
        return self.execution_context.exec_info


class NamedStandardTask(StandardTask, metaclass=abc.ABCMeta):
    """Named Standard Task."""

    init_params = ["task_name"]
    run_params = []

    def __init__(self, task_name: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.task_name = task_name

    @property
    def name(self) -> str:
        return (
            self.task_name
            if self.task_name is not None
            else split_camel_case_string(self.__class__.__name__)
        )
