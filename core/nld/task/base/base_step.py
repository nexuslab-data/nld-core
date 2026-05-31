import abc
from typing import Any, ClassVar

from nld.exceptions import MissingMandatoryArgumentException
from nld.parameters.execution_params_def import (
    ExecutionParameterDefinition,
)
from nld.utils import NldStrEnum
from nld.utils.mixin import NldMixIn


class BaseStepStatus(NldStrEnum):
    SUCCEEDED = "SUCCEEDED"
    SUCCEEDED_WITH_WARNING = "WARNING"
    FAILED = "FAILED"


class BaseStep(NldMixIn, metaclass=abc.ABCMeta):
    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = []
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(self) -> None:
        super().__init__()
        self._init_logger()

    @classmethod
    def check_init_params_dict(cls, params_dict: dict[str, Any]) -> None:
        for init_param in cls.init_params:
            param_name = init_param if isinstance(init_param, str) else init_param.name
            if param_name not in list(params_dict.keys()):
                raise MissingMandatoryArgumentException(cls, "__init__", param_name)

    @classmethod
    def check_run_params_dict(cls, params_dict: dict[str, Any]) -> None:
        for run_param in cls.run_params:
            param_name = run_param if isinstance(run_param, str) else run_param.name
            if param_name not in list(params_dict.keys()):
                raise MissingMandatoryArgumentException(cls, "run", param_name)

    @abc.abstractmethod
    def run(self, **kwargs: Any) -> Any:
        raise Exception(
            f"The run method is not implemented for class : {str(type(self))}"
        )
