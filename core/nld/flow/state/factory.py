import importlib
from typing import Any, cast

from nld.exceptions import ImplementationException
from nld.flow.definition.flow_definition import DataFlowDefinition
from nld.flow.execution import (
    ExecutionStateManagerFactory,
    FlowExecutionInfo,
)
from nld.flow.incremental.services import IncrementalStateManagerFactory
from nld.flow.state.state_backend_connector_resolver import (
    StateBackendConnectorWrapper,
)
from nld.utils.inspect_utils import find_subclass_in_module
from nld.utils.mixin import NldMixIn

from .events import StateManagerLoadSuccessful
from .manager import FlowStateManager


class FlowStateManagerFactory(NldMixIn):
    """
    Factory for creating flow state managers.

    This factory manages IncrementalStateManagerFactory and
    ExecutionStateManagerFactory to create complete FlowStateManager
    instances with all required backend managers.

    Expected module structure:
    - nld.flow.state.manager.{incremental_type}
    """

    def __init__(self) -> None:
        super().__init__()
        self.incremental_state_manager_factory = IncrementalStateManagerFactory()
        self.execution_state_manager_factory = ExecutionStateManagerFactory()
        self.flow_state_managers: dict[
            str, type[FlowStateManager[Any, Any, Any, Any]]
        ] = {}

    def _load_flow_state_manager_class(
        self, incremental_type: str
    ) -> type[FlowStateManager[Any, Any, Any, Any]]:
        """
        Dynamically load the FlowStateManager class for incremental type.

        Args:
            incremental_type: The incremental type name

        Returns:
            The FlowStateManager class

        Raises:
            ImplementationException: If the module or class cannot be loaded
        """
        state_manager_module_path = f"nld.flow.state.manager.{incremental_type}"

        try:
            state_manager_module = importlib.import_module(
                name=state_manager_module_path
            )
        except ModuleNotFoundError as e:
            error_str = str(e)
            expected_module = f"nld.flow.state.manager.{incremental_type}"
            if f"No module named '{expected_module}'" in error_str:
                raise ImplementationException(
                    msg=f"FlowStateManager for incremental type "
                    f"'{incremental_type}' is not available"
                ) from e
            else:
                raise

        manager_class = cast(
            type[FlowStateManager[Any, Any, Any, Any]],
            find_subclass_in_module(
                module=state_manager_module,
                base_class=FlowStateManager,
            ),
        )

        self.flow_state_managers[incremental_type] = manager_class
        self.log_event(StateManagerLoadSuccessful(incremental_type=incremental_type))

        return manager_class

    def get_flow_state_manager_class(
        self, incremental_type: str
    ) -> type[FlowStateManager[Any, Any, Any, Any]]:
        """
        Get the FlowStateManager class for the specified incremental type.

        Args:
            incremental_type: The incremental type name

        Returns:
            The FlowStateManager class for the specified incremental type

        Raises:
            ImplementationException: If the incremental type is not available
        """
        if incremental_type not in self.flow_state_managers:
            return self._load_flow_state_manager_class(
                incremental_type=incremental_type
            )

        return self.flow_state_managers[incremental_type]

    def create_flow_state_manager(
        self,
        incremental_type: str,
        flow_execution_info: FlowExecutionInfo,
        state_backend_connector_wrapper: StateBackendConnectorWrapper | None = None,
        data_flow_definition: DataFlowDefinition | None = None,
        engine: str | None = None,
        **kwargs: Any,
    ) -> FlowStateManager[Any, Any, Any, Any]:
        """
        Create a FlowStateManager instance.

        This method creates all required backend managers and state managers:
        - ExecutionBackendStateManager (optional)
        - ExecutionStateManager (via ExecutionStateManagerFactory)
        - IncrementalBackendStateManager (optional)
        - IncrementalStateManager (via IncrementalStateManagerFactory)
        - FlowStateManager

        Args:
            incremental_type: The incremental type name
            flow_execution_info: The flow execution information. Contains
                flow_namespace and flow_name
            state_backend_connector_wrapper: Live primary/secondary state
                backend sides. When None no backend managers are created.
            engine: The processing engine ('pydantic' or 'duckdb').
                Default: None (pydantic)
            **kwargs: Additional parameters including incremental parameters

        Returns:
            An instantiated FlowStateManager with or without backends

        Raises:
            ImplementationException: If the combination is not available
        """
        execution_state_manager = (
            self.execution_state_manager_factory.create_execution_state_manager(
                current_execution_info=flow_execution_info,
                state_backend_connector_wrapper=state_backend_connector_wrapper,
                data_flow_definition=data_flow_definition,
                engine=engine,
                **kwargs,
            )
        )

        incremental_state_manager = (
            self.incremental_state_manager_factory.create_incremental_state_manager(
                incremental_type=incremental_type,
                state_backend_connector_wrapper=state_backend_connector_wrapper,
                flow_namespace=flow_execution_info.flow_namespace,
                flow_name=flow_execution_info.flow_name,
                engine=engine,
                flow_uid=flow_execution_info.flow_uid,
                data_flow_definition=data_flow_definition,
                **kwargs,
            )
        )

        flow_state_manager_class = self.get_flow_state_manager_class(
            incremental_type=incremental_type
        )

        return flow_state_manager_class(
            execution_state_manager=execution_state_manager,
            incremental_state_manager=incremental_state_manager,
        )
