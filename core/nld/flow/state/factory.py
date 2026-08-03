from typing import Any

from nld.flow.definition.flow_definition import DataFlowDefinition
from nld.flow.execution import (
    ExecutionStateManagerFactory,
    FlowExecutionInfo,
)
from nld.flow.incremental.services import (
    FlowIncrementalTypeRegistry,
    IncrementalStateManagerFactory,
    get_flow_incremental_type_registry,
)
from nld.flow.state.state_backend_connector_resolver import (
    StateBackendConnectorWrapper,
)
from nld.utils.mixin import NldMixIn

from .events import StateManagerLoadSuccessful
from .manager import FlowStateManager


class FlowStateManagerFactory(NldMixIn):
    """
    Factory for creating flow state managers.

    This factory manages IncrementalStateManagerFactory and
    ExecutionStateManagerFactory to create complete FlowStateManager
    instances with all required backend managers.

    The wrapper class is always the single concrete `FlowStateManager`;
    every per-type behavior lives in the incremental state manager
    resolved through the type's `FlowIncrementalTypeRegistry` manifest,
    so external incremental types need no flow-level module at all.
    """

    def __init__(
        self,
        registry: FlowIncrementalTypeRegistry | None = None,
    ) -> None:
        super().__init__()
        self._registry = (
            registry if registry is not None else (get_flow_incremental_type_registry())
        )
        self.incremental_state_manager_factory = IncrementalStateManagerFactory(
            registry=self._registry,
        )
        self.execution_state_manager_factory = ExecutionStateManagerFactory()

    def get_flow_state_manager_class(
        self, incremental_type: str
    ) -> type[FlowStateManager[Any, Any, Any, Any]]:
        """
        Get the FlowStateManager class for the specified incremental type.

        The class is always the generic `FlowStateManager`; the lookup
        only validates that the incremental type is registered.

        Args:
            incremental_type: The incremental type name

        Returns:
            The FlowStateManager class

        Raises:
            ImplementationException: If the incremental type is not available
        """
        self._registry.get(name=incremental_type)
        self.log_event(StateManagerLoadSuccessful(incremental_type=incremental_type))

        return FlowStateManager

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
        kwargs["flow_started_at"] = flow_execution_info.started_at

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
