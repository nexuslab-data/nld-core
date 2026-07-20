from __future__ import annotations

import importlib
import inspect
from typing import TYPE_CHECKING, Any, cast

from nld.exceptions import ImplementationException
from nld.flow.incremental.base.manager import (
    IncrementalBackendStateManager,
    IncrementalStateManager,
)
from nld.flow.incremental.models import (
    FlowIncrementalLogic,
    FlowIncrementalTypeManifest,
)
from nld.flow.incremental.models.events import (
    IncrementalBackendLoadSuccessful,
    IncrementalStateManagerLoadSuccessful,
)
from nld.flow.incremental.services.registry import (
    FlowIncrementalTypeRegistry,
    get_flow_incremental_type_registry,
)
from nld.utils.inspect_utils import find_subclass_in_module
from nld.utils.mixin import NldMixIn

if TYPE_CHECKING:
    from nld.flow.definition.flow_definition import DataFlowDefinition
    from nld.flow.state.state_backend_connector_resolver import (
        StateBackendConnector,
        StateBackendConnectorWrapper,
    )

BASE_BACKEND_TYPE = "base"
DEFAULT_ENGINE = "pydantic"


def _ensure_builtin_manifests_registered() -> None:
    """Import the built-in incremental types package so it self-registers."""
    importlib.import_module(name="nld.flow.incremental.impl")


class IncrementalStateManagerFactory(NldMixIn):
    """
    Factory for creating incremental state managers based on incremental type
    and backend name.

    Resolves modules through `FlowIncrementalTypeRegistry`: each registered
    incremental type carries a `FlowIncrementalTypeManifest` that pins its
    logic / state-manager / backend modules. Built-in types seed themselves
    when their package is first imported; external types are added through
    `AdditionalIncrementalTypeConfig` in `nld_project.yml`.

    Engine support:
    - engine='pydantic' (default): uses standard backend module
    - engine='duckdb': uses DuckDB-optimized backend module
    """

    def __init__(
        self,
        registry: FlowIncrementalTypeRegistry | None = None,
    ) -> None:
        super().__init__()
        _ensure_builtin_manifests_registered()
        self._registry = (
            registry if registry is not None else (get_flow_incremental_type_registry())
        )
        self.incremental_backend_state_managers: dict[
            str,
            dict[
                str, type[IncrementalBackendStateManager[Any, Any, Any, Any, Any, Any]]
            ],
        ] = {}
        self.incremental_state_managers: dict[
            str, type[IncrementalStateManager[Any, Any, Any, Any, Any]]
        ] = {}
        self.incremental_logics: dict[str, FlowIncrementalLogic[Any]] = {}

    def _get_manifest(self, incremental_type: str) -> FlowIncrementalTypeManifest:
        return self._registry.get(name=incremental_type)

    def _load_incremental_backend_state_manager(
        self,
        incremental_type: str,
        backend_type: str,
        engine: str | None = None,
    ) -> type[IncrementalBackendStateManager[Any, Any, Any, Any, Any, Any]]:
        """Dynamically load the IncrementalBackendStateManager class.

        Raises ImplementationException when either the incremental type or the
        backend module cannot be located.
        """
        manifest = self._get_manifest(incremental_type=incremental_type)
        effective_engine = engine if engine else DEFAULT_ENGINE
        backend_module_path = manifest.resolve_backend_module_path(
            backend_type=backend_type,
            engine=effective_engine,
        )

        try:
            backend_module = importlib.import_module(name=backend_module_path)
        except ModuleNotFoundError as e:
            if f"No module named '{manifest.backend_package}" in str(e):
                raise ImplementationException(
                    msg=(
                        f"Backend '{backend_type}' with engine "
                        f"'{effective_engine}' is not available for "
                        f"incremental type '{incremental_type}'"
                    ),
                ) from e
            raise

        manager_class = cast(
            type[IncrementalBackendStateManager[Any, Any, Any, Any, Any, Any]],
            find_subclass_in_module(
                module=backend_module,
                base_class=IncrementalBackendStateManager,
            ),
        )

        cache_key = f"{backend_type}_{effective_engine}"
        self.incremental_backend_state_managers[incremental_type][cache_key] = (
            manager_class
        )
        self.log_event(IncrementalBackendLoadSuccessful(backend_type=backend_type))

        return manager_class

    def get_incremental_backend_state_manager_class(
        self,
        incremental_type: str,
        backend_type: str,
        engine: str | None = None,
    ) -> type[IncrementalBackendStateManager[Any, Any, Any, Any, Any, Any]]:
        """
        Get the IncrementalBackendStateManager class for the specified
        incremental type, backend, and engine.
        """
        manifest = self._get_manifest(incremental_type=incremental_type)
        effective_engine = engine if engine else DEFAULT_ENGINE
        cache_key = f"{backend_type}_{effective_engine}"

        if incremental_type not in self.incremental_backend_state_managers:
            self.incremental_backend_state_managers[incremental_type] = {}

        if cache_key in self.incremental_backend_state_managers[incremental_type]:
            return self.incremental_backend_state_managers[incremental_type][cache_key]

        try:
            return self._load_incremental_backend_state_manager(
                incremental_type=incremental_type,
                backend_type=backend_type,
                engine=engine,
            )
        except ImplementationException as exc:
            if not manifest.fallback_to_base_backend:
                raise

            manager_class = self._load_incremental_backend_state_manager(
                incremental_type=incremental_type,
                backend_type=BASE_BACKEND_TYPE,
                engine=engine,
            )
            if inspect.isabstract(manager_class):
                msg = (
                    f"Backend '{backend_type}' with engine "
                    f"'{effective_engine}' is not available for "
                    f"incremental type '{incremental_type}'"
                )
                raise ImplementationException(msg=msg) from exc
            return manager_class

    def create_incremental_backend_state_manager(
        self,
        incremental_type: str,
        state_backend_connector: StateBackendConnector,
        flow_namespace: str,
        flow_name: str,
        data_flow_definition: DataFlowDefinition | None = None,
        engine: str | None = None,
        **kwargs: Any,
    ) -> IncrementalBackendStateManager[Any, Any, Any, Any, Any, Any]:
        """Create an IncrementalBackendStateManager for one state-backend side.

        Engine resolution precedence (highest first):

        1. Explicit ``engine=`` keyword argument (flow-level override).
        2. ``state_backend_connector.config.params["engine"]`` declared
           in YAML on this side of the wrapper.
        3. ``DEFAULT_ENGINE``.

        Backend parameters are merged with the following precedence
        (lowest to highest):

        1. Parameters derived from the typed flow context (for example
           ``s3_root_path`` from an ``S3Structure`` target) via the
           backend manager's ``determine_parameters_for_flow_definition``.
        2. ``state_backend_connector.config.params`` declared in YAML
           on this side of the wrapper.
        3. Explicit keyword arguments passed by the caller.

        This is the same precedence applied by
        ``ExecutionStateManagerFactory.create_execution_backend_state_manager``.
        """
        backend_type = state_backend_connector.data_connector.connection_wrapper.type
        # Engine is a meta-parameter that selects which backend module
        # to load; strip it from the state-backend connector config
        # params before they are filtered against the backend's
        # declared parameters.
        connector_config_params = dict(state_backend_connector.config.params)
        connector_config_engine = connector_config_params.pop("engine", None)
        effective_engine = engine or connector_config_engine
        manager_class = self.get_incremental_backend_state_manager_class(
            incremental_type=incremental_type,
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

    def _load_incremental_state_manager(
        self, incremental_type: str
    ) -> type[IncrementalStateManager[Any, Any, Any, Any, Any]]:
        """Dynamically load the IncrementalStateManager class."""
        manifest = self._get_manifest(incremental_type=incremental_type)
        manager_module = importlib.import_module(name=manifest.state_manager_module)

        manager_class = cast(
            type[IncrementalStateManager[Any, Any, Any, Any, Any]],
            find_subclass_in_module(
                module=manager_module,
                base_class=IncrementalStateManager,
            ),
        )

        self.incremental_state_managers[incremental_type] = manager_class
        self.log_event(
            IncrementalStateManagerLoadSuccessful(incremental_type=incremental_type)
        )

        return manager_class

    def _load_incremental_logic(
        self, incremental_type: str
    ) -> FlowIncrementalLogic[Any]:
        """Dynamically load the FlowIncrementalLogic instance."""
        manifest = self._get_manifest(incremental_type=incremental_type)
        logic_module = importlib.import_module(name=manifest.logic_module)

        for attr_name in dir(logic_module):
            attr = getattr(logic_module, attr_name)
            if isinstance(attr, FlowIncrementalLogic):
                self.incremental_logics[incremental_type] = attr
                return attr

        raise ImplementationException(
            msg=(
                f"No FlowIncrementalLogic found for incremental type "
                f"'{incremental_type}'"
            ),
        )

    def get_incremental_state_manager_class(
        self, incremental_type: str
    ) -> type[IncrementalStateManager[Any, Any, Any, Any, Any]]:
        """Get the IncrementalStateManager class for the specified type."""
        if incremental_type not in self.incremental_state_managers:
            self._load_incremental_state_manager(incremental_type=incremental_type)

        return self.incremental_state_managers[incremental_type]

    def get_incremental_logic(self, incremental_type: str) -> FlowIncrementalLogic[Any]:
        """Get the FlowIncrementalLogic for the specified incremental type."""
        if incremental_type not in self.incremental_logics:
            self._load_incremental_logic(incremental_type=incremental_type)

        return self.incremental_logics[incremental_type]

    def create_incremental_state_manager(
        self,
        incremental_type: str,
        state_backend_connector_wrapper: StateBackendConnectorWrapper | None = None,
        flow_namespace: str | None = None,
        flow_name: str | None = None,
        flow_uid: str | None = None,
        data_flow_definition: DataFlowDefinition | None = None,
        engine: str | None = None,
        **kwargs: Any,
    ) -> IncrementalStateManager[Any, Any, Any, Any, Any]:
        """Create an IncrementalStateManager for the specified incremental type.

        Each side (primary / secondary) of the wrapper is built
        independently and merges its own ``config.params``.
        """
        incremental_backend_manager = None
        secondary_incremental_backend_manager = None

        if state_backend_connector_wrapper is not None:
            if flow_namespace is None:
                raise ValueError(
                    "flow_namespace is required when "
                    "state_backend_connector_wrapper is provided"
                )
            if flow_name is None:
                raise ValueError(
                    "flow_name is required when "
                    "state_backend_connector_wrapper is provided"
                )

            incremental_backend_manager = self.create_incremental_backend_state_manager(
                incremental_type=incremental_type,
                state_backend_connector=state_backend_connector_wrapper.primary,
                flow_namespace=flow_namespace,
                flow_name=flow_name,
                data_flow_definition=data_flow_definition,
                engine=engine,
                **kwargs,
            )

            if state_backend_connector_wrapper.secondary is not None:
                secondary_incremental_backend_manager = (
                    self.create_incremental_backend_state_manager(
                        incremental_type=incremental_type,
                        state_backend_connector=(
                            state_backend_connector_wrapper.secondary
                        ),
                        flow_namespace=flow_namespace,
                        flow_name=flow_name,
                        data_flow_definition=data_flow_definition,
                        engine=engine,
                        **kwargs,
                    )
                )

        incremental_logic = self.get_incremental_logic(
            incremental_type=incremental_type,
        )

        incremental_parameters = incremental_logic.create_incremental_params_from_dict(
            **kwargs,
        )

        manager_class = self.get_incremental_state_manager_class(
            incremental_type=incremental_type,
        )

        parameters: dict[str, Any] = {}
        if flow_uid is not None:
            parameters["flow_uid"] = flow_uid
        parameters.update(
            {
                key: value
                for key, value in kwargs.items()
                if key in manager_class.get_param_definitions_keys()
            }
        )

        return manager_class(
            incremental_parameters=incremental_parameters,
            incremental_state_backend_manager=incremental_backend_manager,
            secondary_incremental_state_backend_manager=(
                secondary_incremental_backend_manager
            ),
            parameters=parameters,
        )
