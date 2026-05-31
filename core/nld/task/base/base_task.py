import abc
import uuid
from enum import Flag
from typing import Any, ClassVar

from nld.exceptions import MissingMandatoryArgumentException
from nld.parameters.execution_params_def import (
    ExecutionParameterDefinition,
)
from nld.utils.inspect_utils import get_method_param_type_hints
from nld.utils.mixin import NldMixIn


class BaseRunStatus(Flag):
    SUCCESS = True
    FAIL = False


class BaseTask(NldMixIn, metaclass=abc.ABCMeta):
    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = []
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(self, exec_uuid: str | None = None) -> None:
        super().__init__()
        self._init_logger()
        self.exec_uuid = uuid.uuid4().__str__() if exec_uuid is None else exec_uuid

    @classmethod
    def get_init_params(cls) -> list[ExecutionParameterDefinition]:
        return [
            (
                init_param
                if isinstance(init_param, ExecutionParameterDefinition)
                else ExecutionParameterDefinition(name=init_param)
            )
            for init_param in cls.init_params
        ]

    @classmethod
    def get_init_params_keys(cls) -> list[str]:
        return [init_param.name for init_param in cls.get_init_params()]

    @classmethod
    def check_init_params_dict(cls, params_dict: dict[str, Any]) -> None:
        """
        Check that all mandatory init parameters are present.

        Args:
            params_dict: Dictionary of parameters to validate

        Raises:
            MissingMandatoryArgumentException: If mandatory parameter is missing
        """
        for init_param in cls.get_init_params():
            if init_param.name not in params_dict.keys():
                if init_param.mandatory:
                    raise MissingMandatoryArgumentException(
                        object_type=cls,
                        method_name="check_init_params_dict",
                        argument_name=init_param.name,
                    )

    @classmethod
    def get_init_param_type_hints(cls) -> dict[str, type[Any]]:
        """Extract parameter type hints from __init__ method."""
        return get_method_param_type_hints(cls=cls, method_name="__init__")

    @classmethod
    def get_run_params(cls) -> list[ExecutionParameterDefinition]:
        return [
            (
                run_param
                if isinstance(run_param, ExecutionParameterDefinition)
                else ExecutionParameterDefinition(name=run_param)
            )
            for run_param in cls.run_params
        ]

    @classmethod
    def get_run_params_keys(cls) -> list[str]:
        return [run_param.name for run_param in cls.get_run_params()]

    @classmethod
    def check_run_params_dict(cls, params_dict: dict[str, Any]) -> None:
        """
        Check that all mandatory run parameters are present.

        Args:
            params_dict: Dictionary of parameters to validate

        Raises:
            MissingMandatoryArgumentException: If mandatory parameter is missing
        """
        for run_param in cls.get_run_params():
            if run_param.name not in params_dict.keys():
                if run_param.mandatory:
                    raise MissingMandatoryArgumentException(
                        object_type=cls,
                        method_name="check_run_params_dict",
                        argument_name=run_param.name,
                    )

    @classmethod
    def get_run_param_type_hints(cls) -> dict[str, type[Any]]:
        """Extract parameter type hints from run method."""
        return get_method_param_type_hints(cls=cls, method_name="run")

    @abc.abstractmethod
    def run(self, **kwargs: Any) -> Any:
        raise Exception(
            f"The run method is not implemented for class : {str(type(self))}"
        )
