import traceback
from importlib import import_module
from typing import Any, cast

from nld.exceptions import NldRuntimeException
from nld.flow.definition.flow_definition import DataFlowDefinition
from nld.flow.execution.events import (
    ExecutionBackendImportError,
    ExecutionBackendLoadError,
    ExecutionBackendLoadSuccessful,
)
from nld.flow.execution.execution_info import FlowExecutionInfo
from nld.flow.execution.manager import (
    ExecutionBackendStateManager,
    ExecutionStateManager,
)
from nld.flow.state.state_backend_connector_resolver import (
    StateBackendConnector,
    StateBackendConnectorWrapper,
)
from nld.utils.inspect_utils import find_subclass_in_module
from nld.utils.mixin import NldMixIn


class ExecutionStateManagerFactory(NldMixIn):
    """
    Factory for creating ExecutionBackendStateManager instances.

    This factory dynamically loads backend-specific state managers based on
    a backend type key (e.g., 's3_blob_storage', 'azure_blob_storage') and
    an optional engine type (e.g., 'pydantic', 'duckdb').

    Usage:
        factory = ExecutionStateManagerFactory()
        manager_class = factory.get_backend_manager_class('s3_blob_storage')
        manager = manager_class(...)

        # With DuckDB engine
        manager_class = factory.get_backend_manager_class(
            's3_blob_storage', engine='duckdb'
        )
    """

    def __init__(self) -> None:
        super().__init__()
        self.backend_managers: dict[str, type[ExecutionBackendStateManager[Any]]] = {}

    def _get_module_name(self, backend_type: str, engine: str | None) -> str:
        """
        Get the module name for a backend type and engine combination.

        Parameters
        ----------
        backend_type : str
            The backend type key (e.g., 's3_blob_storage')
        engine : str | None
            The processing engine ('pydantic' or 'duckdb').
            If None, defaults to 'pydantic'.

        Returns
        -------
        str
            The module name to import
        """
        effective_engine = engine if engine else "pydantic"
        return f"{backend_type}_with_{effective_engine}"

    def load_backend_manager_class(
        self, backend_type: str, engine: str | None = None
    ) -> type[ExecutionBackendStateManager[Any]]:
        """
        Load a backend manager class by backend type and engine.

        Parameters
        ----------
        backend_type : str
            The backend type key (e.g., 's3_blob_storage')
        engine : str | None
            The processing engine ('pydantic' or 'duckdb'). Default: None (pydantic)

        Returns
        -------
        Type[ExecutionBackendStateManager]
            The backend manager class

        Raises
        ------
        NldRuntimeException
            If the backend type cannot be found or loaded
        """
        effective_engine = engine if engine else "pydantic"
        module_name = self._get_module_name(backend_type, engine)
        cache_key = f"{backend_type}_{effective_engine}"

        try:
            # Import the module from the backend package
            # e.g., 's3_blob_storage' -> .execution.backend.s3_blob_storage
            mod: Any = import_module(
                "." + module_name,
                "nld.flow.execution.backend",
            )
        except ModuleNotFoundError as exc:
            # If we failed to import the target module in particular, inform
            # the user about it via a runtime error
            if exc.name == f"nld.flow.execution.backend.{module_name}":
                self.log_event(
                    ExecutionBackendImportError(backend_type=backend_type, exc=str(exc))
                )
                raise NldRuntimeException(
                    f"Could not find execution backend type '{backend_type}' "
                    f"with engine '{effective_engine}'! "
                    f"Make sure the module exists at "
                    f"nld.flow.execution.backend.{module_name}"
                ) from exc
            # Otherwise, the error had to have come from some underlying
            # library. Log the stack trace.
            self.log_event(ExecutionBackendLoadError(exc_info=traceback.format_exc()))
            raise

        # Try to find the manager class in the module (ends with Manager)
        manager_class = cast(
            type[ExecutionBackendStateManager[Any]],
            find_subclass_in_module(
                module=mod,
                base_class=ExecutionBackendStateManager,
            ),
        )

        self.backend_managers[cache_key] = manager_class
        self.log_event(ExecutionBackendLoadSuccessful(backend_type=backend_type))

        return manager_class

    def get_backend_manager_class(
        self, backend_type: str, engine: str | None = None
    ) -> type[ExecutionBackendStateManager[Any]]:
        """
        Get a backend manager class by backend type and engine.

        If the backend has not been loaded yet, it will be loaded automatically.

        Parameters
        ----------
        backend_type : str
            The backend type key (e.g., 's3_blob_storage')
        engine : str | None
            The processing engine ('pydantic' or 'duckdb'). Default: None (pydantic)

        Returns
        -------
        Type[ExecutionBackendStateManager]
            The backend manager class

        Raises
        ------
        NldRuntimeException
            If the backend type cannot be found
        """
        effective_engine = engine if engine else "pydantic"
        cache_key = f"{backend_type}_{effective_engine}"
        if cache_key not in self.backend_managers:
            return self.load_backend_manager_class(backend_type, engine=engine)

        return self.backend_managers[cache_key]

    def create_execution_backend_state_manager(
        self,
        state_backend_connector: StateBackendConnector,
        flow_namespace: str,
        flow_name: str,
        data_flow_definition: DataFlowDefinition | None = None,
        engine: str | None = None,
        **kwargs: Any,
    ) -> ExecutionBackendStateManager[Any]:
        """Create an ExecutionBackendStateManager for one state-backend side.

        ``state_backend_connector`` carries the live ``DataConnector``
        (used to derive the backend type and to instantiate the manager)
        and the per-side config (whose ``params`` feed into the manager
        parameters). The wrapper-aware sibling
        ``create_execution_state_manager`` builds primary and secondary
        managers from a ``StateBackendConnectorWrapper``.

        Engine resolution precedence (highest first):

        1. Explicit ``engine=`` keyword argument (flow-level override).
        2. ``state_backend_connector.config.params["engine"]`` declared
           in YAML on this side of the wrapper.
        3. Default engine (``pydantic``).

        Backend parameters are merged with the following precedence
        (lowest to highest):

        1. Parameters derived from the typed flow context (for example
           ``s3_root_path`` from an ``S3Structure`` target) via the
           backend manager's ``determine_parameters_for_flow_definition``.
        2. ``state_backend_connector.config.params`` declared in YAML
           on this side of the wrapper.
        3. Explicit keyword arguments passed by the caller.

        This is the same precedence applied by
        ``IncrementalStateManagerFactory.create_incremental_backend_state_manager``.
        """
        backend_type = state_backend_connector.data_connector.connection_wrapper.type
        # Engine is a meta-parameter that selects which backend module
        # to load; strip it from the state-backend connector config
        # params before they are filtered against the backend's
        # declared parameters.
        connector_config_params = dict(state_backend_connector.config.params)
        connector_config_engine = connector_config_params.pop("engine", None)
        effective_engine = engine or connector_config_engine
        manager_class = self.get_backend_manager_class(
            backend_type=backend_type,
            engine=effective_engine,
        )

        derived = manager_class.determine_parameters_for_flow_definition(
            data_flow_definition=data_flow_definition,
        )
        merged: dict[str, Any] = {
            **derived,
            **connector_config_params,
            **kwargs,
        }

        parameters: dict[str, Any] = {
            key: value
            for key, value in merged.items()
            if key in manager_class.get_param_definitions_keys()
        }
        manager_class.check_param_definitions_dict(parameters)

        return manager_class(
            backend_connector=state_backend_connector.data_connector,
            flow_namespace=flow_namespace,
            flow_name=flow_name,
            parameters=parameters,
        )

    def create_execution_state_manager(
        self,
        current_execution_info: FlowExecutionInfo,
        state_backend_connector_wrapper: StateBackendConnectorWrapper | None = None,
        data_flow_definition: DataFlowDefinition | None = None,
        engine: str | None = None,
        **kwargs: Any,
    ) -> ExecutionStateManager:
        """Create an ExecutionStateManager from a state-backend wrapper.

        When the wrapper is None, no backend managers are created and
        the returned ExecutionStateManager runs without persistence.
        """
        execution_backend_state_manager = None
        secondary_execution_backend_state_manager = None

        if state_backend_connector_wrapper is not None:
            execution_backend_state_manager = (
                self.create_execution_backend_state_manager(
                    state_backend_connector=state_backend_connector_wrapper.primary,
                    flow_namespace=current_execution_info.flow_namespace,
                    flow_name=current_execution_info.flow_name,
                    data_flow_definition=data_flow_definition,
                    engine=engine,
                    **kwargs,
                )
            )

            if state_backend_connector_wrapper.secondary is not None:
                secondary_execution_backend_state_manager = (
                    self.create_execution_backend_state_manager(
                        state_backend_connector=(
                            state_backend_connector_wrapper.secondary
                        ),
                        flow_namespace=current_execution_info.flow_namespace,
                        flow_name=current_execution_info.flow_name,
                        data_flow_definition=data_flow_definition,
                        engine=engine,
                        **kwargs,
                    )
                )

        return ExecutionStateManager(
            current_execution_info=current_execution_info,
            execution_state_backend_manager=execution_backend_state_manager,
            secondary_execution_state_backend_manager=(
                secondary_execution_backend_state_manager
            ),
        )
