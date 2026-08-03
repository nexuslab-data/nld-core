from types import ModuleType
from typing import TYPE_CHECKING, Any

from pydantic import Field as PydanticField
from pydantic import field_validator, model_validator

from nld.flow.config import (
    ConnectorConfig,
    StateBackendConnectorConfigWrapper,
    coerce_connector_config,
)
from nld.flow.definition.field_lineage import FieldLineage
from nld.flow.definition.sql_config import SQLConfig
from nld.flow.incremental.models import FlowIncrementalLogic, IncrementalConfig
from nld.flow.quality.models import DataQualityChecksConfig
from nld.flow.quality.service import validate_quality_checks
from nld.misc import EnvironmentVariableDefinition
from nld.parameters import ExecutionParameter, create_model_dict
from nld.pydantic import (
    NldBaseModel,
    NldEntityReference,
    NldNamedBaseModel,
    NldNamespace,
    NldNamespacedBaseModelWrapper,
)
from nld.structure import Structure
from nld.utils import ModuleLoader, format_exception_chain
from nld.utils.inspect_utils import find_subclass_in_module

# Intentional circular dependency: DataFlowDefinition is the entry point for
# flow loading, and DataFlowTask imports it at runtime. Keeping that
# back-reference as a TYPE_CHECKING annotation avoids the cycle.
if TYPE_CHECKING:
    from nld.flow.task import DataFlowTask

ROOT_NAMESPACE: str = NldNamespace.ROOT_VALUE


DEFAULT_FLOW_TASK_TYPES: dict[str, str] = {
    "seed": "nld.flow.seed.seed_flow_task.SeedFlowTask",
    "sql": "nld.flow.sql.sql_flow_task.SQLFlowTask",
}

MASTER_PREDECESSOR_ROLE = "MASTER"


class DataFlowStructurePredecessor(NldBaseModel):
    """A predecessor structure dependency for a data flow definition."""

    full_path: NldEntityReference[Structure]
    key_field: str | None = None
    role: str | None = None

    def is_master(self) -> bool:
        """Check if this predecessor has the MASTER role."""
        return self.role == MASTER_PREDECESSOR_ROLE


def resolve_master_predecessors(
    predecessors: dict[str, DataFlowStructurePredecessor],
) -> list[tuple[str, DataFlowStructurePredecessor]]:
    """Find all MASTER predecessors.

    Returns a list of all predecessors with role MASTER.
    When there is exactly one predecessor and its role is not
    explicitly set, it defaults to MASTER.
    Returns an empty list if no predecessors exist or none
    have the MASTER role.
    """
    explicit_masters = [
        (predecessor_name, predecessor)
        for predecessor_name, predecessor in predecessors.items()
        if predecessor.is_master()
    ]
    if explicit_masters:
        return explicit_masters

    if len(predecessors) == 1:
        predecessor_name, predecessor = next(iter(predecessors.items()))
        if predecessor.role is None:
            return [(predecessor_name, predecessor)]

    return []


class TaskModuleNotLoadedError(Exception):
    """Raised when task module is accessed before being loaded."""


class DataFlowDefinition(NldNamedBaseModel):
    """
    The definition of a data flow.

    A definition contains:
    - The task class (optional - can be auto-resolved from namespace and flow name)
    - The data connectors mapping linking the name of the standard connectors
      of the task to the connector name to use
    - The execution parameters
        - All parameters should match the execution parameter model and be
          associated to a NldBaseModel
        - Parameters will be split between init and run based on the task's
          init_params and run_params declarations

    When task is not provided, it will be auto-resolved using the path:
    <entity_path>.flows.<namespace>.<flow_name> and searching for a
    DataFlowTask subclass in that module.

    Before using methods that require the task class (get_init_params_keys,
    get_params_model_dict_for_init, etc.), you must call load_task_module()
    to initialize the task module.
    """

    task: str | None = None
    task_type: str | None = None
    state_backend_connector: StateBackendConnectorConfigWrapper | None = None
    data_connectors: dict[str, ConnectorConfig] | None = None
    variables: list[EnvironmentVariableDefinition] | None = None
    incremental: IncrementalConfig | None = None
    params: list[ExecutionParameter] | None = None
    predecessors: dict[str, DataFlowStructurePredecessor] = PydanticField(
        default_factory=dict
    )
    sql: SQLConfig | None = None
    target_from_sources_mapping: dict[str, FieldLineage] | None = None
    target_structure: NldEntityReference[Structure] | None = None
    write_strategy: str | None = None
    quality_checks: DataQualityChecksConfig | None = None

    @field_validator("target_from_sources_mapping", mode="before")
    @classmethod
    def normalize_target_from_sources_mapping(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Normalize string values into FieldLineage dicts."""
        if value is None:
            return value
        return {
            key: {"origin": val} if isinstance(val, str) else val
            for key, val in value.items()
        }

    @field_validator("incremental", mode="before")
    @classmethod
    def normalize_incremental(
        cls,
        value: str | dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Normalize a plain string into an IncrementalConfig dict."""
        if isinstance(value, str):
            return {"type": value}
        return value

    @field_validator("quality_checks", mode="before")
    @classmethod
    def normalize_quality_checks(
        cls,
        value: Any,
    ) -> Any:
        """Normalize the shorthand forms of ``quality_checks``.

        Accepts, in addition to the canonical mapping: ``false`` to
        disable the whole step, ``true`` as an explicit no-op, and a
        bare list of checks.
        """
        if value is False:
            return {"enabled": False}
        if value is True:
            return {}
        if isinstance(value, list):
            return {"checks": value}
        return value

    @field_validator("params", mode="before")
    @classmethod
    def normalize_dict_params(
        cls,
        value: dict[str, Any] | list[Any] | None,
    ) -> list[dict[str, Any]] | None:
        """Normalize dict-format params into list of ExecutionParameter dicts."""
        if isinstance(value, dict):
            return [
                {"name": key, "value": param_value}
                for key, param_value in value.items()
            ]
        return value

    @field_validator("variables", mode="before")
    @classmethod
    def normalize_variables(
        cls,
        value: dict[str, Any] | list[Any] | None,
    ) -> list[dict[str, Any]] | None:
        """Normalize the shorthand forms of ``variables``.

        Accepts, in addition to the canonical list of dicts:
        - a bare string item (just the variable name), and
        - a mapping ``{NAME: {attrs}}`` or ``{NAME: null}`` (name keyed).
        """
        if value is None:
            return value
        if isinstance(value, dict):
            return [{"name": name, **(attrs or {})} for name, attrs in value.items()]
        return [{"name": item} if isinstance(item, str) else item for item in value]

    @field_validator("data_connectors", mode="before")
    @classmethod
    def coerce_data_connectors(
        cls,
        value: Any,
    ) -> Any:
        """Coerce each ``data_connectors`` entry into a ``ConnectorConfig``.

        A bare connection-name string is the common case and is promoted to
        ``{connector: <name>}``; a mapping value is passed through so a flow
        can pin a profile per connection::

            data_connectors:
              source_connector: my_lake                # name only
              target_connector:
                connector: my_warehouse
                profile_name: staging
        """
        if not isinstance(value, dict):
            return value
        return {
            connector_name: coerce_connector_config(connector_value)
            for connector_name, connector_value in value.items()
        }

    @field_validator("state_backend_connector", mode="before")
    @classmethod
    def normalize_state_backend_connector(
        cls,
        value: Any,
    ) -> Any:
        # Preserves the legacy YAML form where state_backend_connector was a
        # bare connection-name string, by promoting it to the primary slot.
        if isinstance(value, str):
            return {"primary": value}
        return value

    @model_validator(mode="after")
    def validate_task_and_task_type_mutually_exclusive(self) -> "DataFlowDefinition":
        """Ensure task and task_type are not both set."""
        if self.task is not None and self.task_type is not None:
            raise ValueError(
                "'task' and 'task_type' are mutually exclusive. "
                "Use 'task' for a full module path or 'task_type' for "
                "a shorthand type name, but not both."
            )
        return self

    # Private attribute to cache the loaded task module
    _task_module: tuple[ModuleType, type["DataFlowTask"]] | None = None
    _additional_task_paths: list[str] | None = None
    _resolved_target_structure: Structure | None = None
    _resolved_incremental_logic: FlowIncrementalLogic[Any] | None = None

    def resolve_target_dialect(self) -> str | None:
        """Resolve the sqlglot dialect from the target structure's connector type."""
        if self.target_structure is None:
            return None
        target_structure = self.resolve_target_structure()
        if target_structure.connector_type is None:
            return None
        from nld.connector.base import resolve_sqlglot_dialect

        return resolve_sqlglot_dialect(target_structure.connector_type)

    @property
    def has_quality_checks(self) -> bool:
        """Whether the definition declares at least one data quality check.

        Pure configuration presence: disabled checks and a disabled block
        still count as declared. Use ``has_quality_checks_enabled`` to know
        whether the quality step will actually run.
        """
        return self.quality_checks is not None and len(self.quality_checks.checks) > 0

    @property
    def has_quality_checks_enabled(self) -> bool:
        """Whether at least one declared data quality check will run."""
        if self.quality_checks is None or not self.quality_checks.enabled:
            return False
        return any(check.enabled for check in self.quality_checks.checks)

    def resolve_target_structure(self) -> Structure:
        """Resolve the target_structure reference to a deep-copied Structure."""
        if self.target_structure is None:
            raise ValueError(f"target_structure is not set on flow '{self.name}'")
        if self._resolved_target_structure is not None:
            return self._resolved_target_structure

        from nld.service.nld_entity_registry import EntityTypeNames

        self._resolved_target_structure = self.target_structure.resolve(
            entity_type=EntityTypeNames.STRUCTURE,
        )
        return self._resolved_target_structure

    def get_variables(self) -> list[EnvironmentVariableDefinition]:
        """Return the variables declared on this flow."""
        return self.variables or []

    def get_connector_keys(self) -> list[str]:
        keys = (
            list(self.data_connectors.keys())
            if self.data_connectors is not None
            else []
        )
        if self.state_backend_connector is not None:
            keys.append("state_backend")
            if self.state_backend_connector.secondary is not None:
                keys.append("secondary_state_backend")
        return keys

    def get_connector_connection_names(self) -> set[str]:
        names: set[str] = set()
        if self.data_connectors is not None:
            names.update(
                connector_config.connector
                for connector_config in self.data_connectors.values()
            )
        if self.state_backend_connector is not None:
            names.add(self.state_backend_connector.primary.connector)
            if self.state_backend_connector.secondary is not None:
                names.add(self.state_backend_connector.secondary.connector)
        return names

    def resolve_master_predecessors(
        self,
    ) -> list[tuple[str, DataFlowStructurePredecessor]]:
        """Delegate to the module-level resolve_master_predecessors function."""
        return resolve_master_predecessors(self.predecessors)

    def check_coherence(
        self,
        namespace: str | None = None,
        entity_path: str | None = None,
        additional_task_paths: list[str] | None = None,
        additional_flow_task_types: dict[str, str] | None = None,
    ) -> tuple[bool, list[str]]:
        """
        Check the coherence of the data flow definition.

        This method validates:
        - The task module can be loaded
        - All params can be instantiated correctly

        Args:
            namespace: The namespace of the data flow
            entity_path: The entity path from project
            additional_task_paths: Optional additional paths for module loading
            additional_flow_task_types: User-configured task type mappings

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors: list[str] = []

        if not self._check_task_module(
            namespace=namespace,
            entity_path=entity_path,
            additional_task_paths=additional_task_paths,
            additional_flow_task_types=additional_flow_task_types,
            errors=errors,
        ):
            return False, errors

        # Load the task module for use by other methods
        self.load_task_module(
            namespace=namespace,
            entity_path=entity_path,
            additional_task_paths=additional_task_paths,
            additional_flow_task_types=additional_flow_task_types,
        )

        self._check_params(
            errors=errors,
            additional_task_paths=additional_task_paths,
        )

        self._check_quality_checks(errors=errors)

        return len(errors) == 0, errors

    def _check_quality_checks(self, errors: list[str]) -> None:
        """Validate the quality_checks block against the available rules.

        Column existence is validated best-effort: outside a loaded entity
        registry the target structure cannot resolve, and the rule and
        param validation must still surface. Declared checks are validated
        even when disabled — they stay part of the configuration and may
        be re-enabled at any time.
        """
        if not self.has_quality_checks:
            return
        target_structure: Structure | None = None
        if self.target_structure is not None:
            try:
                target_structure = self.resolve_target_structure()
            except Exception:
                target_structure = None
        errors.extend(
            validate_quality_checks(
                quality_checks=self.quality_checks,
                target_structure=target_structure,
            ),
        )

    def _resolve_task_module_path(
        self,
        namespace: str | None = None,
        entity_path: str | None = None,
        additional_flow_task_types: dict[str, str] | None = None,
    ) -> str:
        """
        Resolve the task module path from task, task_type, or namespace.

        Resolution order:
        1. If task is set, return it directly.
        2. If task_type is set, resolve from additional_flow_task_types
           then DEFAULT_FLOW_TASK_TYPES.
        3. Otherwise, auto-resolve from namespace and flow name.

        Args:
            namespace: The namespace of the data flow
            entity_path: The entity path from project configuration
            additional_flow_task_types: User-configured task type mappings

        Returns:
            The resolved module path string

        Raises:
            ValueError: If task_type is unknown or namespace missing for
                auto-resolution
        """
        if self.task is not None:
            return self.task

        if self.task_type is not None:
            if (
                additional_flow_task_types
                and self.task_type in additional_flow_task_types
            ):
                return additional_flow_task_types[self.task_type]
            if self.task_type in DEFAULT_FLOW_TASK_TYPES:
                return DEFAULT_FLOW_TASK_TYPES[self.task_type]

            available_types = sorted(
                set(DEFAULT_FLOW_TASK_TYPES.keys())
                | set((additional_flow_task_types or {}).keys())
            )
            raise ValueError(
                f"Unknown task_type '{self.task_type}' in flow '{self.name}'. "
                f"Available task types: {available_types}"
            )

        if namespace is None:
            raise ValueError(
                f"Cannot auto-resolve task for flow '{self.name}': "
                f"namespace is required when task is not specified"
            )

        # Build the module path: <entity_path>.flows.<namespace>.<flow_name>
        path_parts = []

        # Add entity_path if provided and not root
        if entity_path is not None and not NldNamespace(entity_path).is_root:
            path_parts.append(entity_path.replace("/", ".").replace("\\", "."))

        # Add 'flows' directory
        path_parts.append("flows")

        # Add namespace if not root
        if not NldNamespace(namespace).is_root:
            path_parts.append(namespace)

        # Add flow name
        path_parts.append(self.name)

        return ".".join(path_parts)

    def resolve_task_module(
        self,
        namespace: str | None = None,
        entity_path: str | None = None,
        additional_task_paths: list[str] | None = None,
        additional_flow_task_types: dict[str, str] | None = None,
    ) -> tuple[ModuleType, type["DataFlowTask"]]:
        """
        Get the task module.

        When task or task_type is explicitly provided, loads it using
        ModuleLoader.load_class(). When neither is set, auto-resolves
        the module path from namespace and flow name, then searches for
        a DataFlowTask subclass in that module.

        Args:
            namespace: The namespace of the data flow
            entity_path: The entity path from project
            additional_task_paths: Optional additional paths for module loading
            additional_flow_task_types: User-configured task type mappings

        Returns:
            Tuple containing the module and task class

        Raises:
            ValueError: If resolution fails or task is not a DataFlowTask
        """
        from nld.flow.task import DataFlowTask

        has_explicit_path = self.task is not None or self.task_type is not None

        if has_explicit_path:
            resolved_path = self._resolve_task_module_path(
                additional_flow_task_types=additional_flow_task_types,
            )
            # An explicit fully-qualified path (containing a dot) must bind to
            # exactly what the YAML asked for. Falling back to additional paths
            # would strip it to a bare class name, hide the real import failure,
            # and risk silently binding to a same-named class elsewhere.
            resolved_path_is_fqn = "." in resolved_path
            loader = ModuleLoader(additional_paths=additional_task_paths or [])
            module, task_class = loader.load_class(
                path_or_class_name=resolved_path,
                try_to_import_from_additional_paths=(
                    bool(additional_task_paths) and not resolved_path_is_fqn
                ),
            )
            if not issubclass(task_class, DataFlowTask):
                raise ValueError(
                    f"Task module '{task_class.__name__}' is not a DataFlowTask."
                )
            return module, task_class

        # Auto-resolve task from namespace and flow name
        module_path = self._resolve_task_module_path(
            namespace=namespace,
            entity_path=entity_path,
        )

        loader = ModuleLoader(additional_paths=additional_task_paths or [])
        try:
            module = loader.load_module(module_path=module_path)
        except ModuleNotFoundError as exc:
            # Only wrap when the resolved module itself (or one of its parent
            # packages) is missing. A different missing name means the flow
            # module was found but one of its own imports failed - in that case
            # the original exception is the actionable one and must propagate.
            missing = exc.name or ""
            target_missing = missing == module_path or (
                missing and module_path.startswith(missing + ".")
            )
            if not target_missing:
                raise
            raise ValueError(
                f"Cannot auto-resolve task for flow '{self.name}' in "
                f"namespace '{namespace}': module '{module_path}' not found. "
                f"Either provide an explicit 'task' in the flow definition or "
                f"create a Python file at the expected path with a DataFlowTask "
                f"subclass."
            ) from exc

        task_class = find_subclass_in_module(
            module=module,
            base_class=DataFlowTask,
        )

        return module, task_class

    def load_task_module(
        self,
        namespace: str | None = None,
        entity_path: str | None = None,
        additional_task_paths: list[str] | None = None,
        additional_flow_task_types: dict[str, str] | None = None,
    ) -> None:
        """
        Load and cache the task module for this flow definition.

        This method must be called before using methods that require the task
        class, such as get_init_params_keys, get_params_model_dict_for_init,
        get_run_params_keys, get_params_model_dict_for_run.

        Args:
            namespace: The namespace of the data flow
            entity_path: The entity path from project
            additional_task_paths: Optional list of additional paths for module loading
            additional_flow_task_types: User-configured task type mappings
        """
        self._task_module = self.resolve_task_module(
            namespace=namespace,
            entity_path=entity_path,
            additional_task_paths=additional_task_paths,
            additional_flow_task_types=additional_flow_task_types,
        )
        self._additional_task_paths = additional_task_paths

    def _require_task_module(self) -> tuple[ModuleType, type["DataFlowTask"]]:
        """
        Get the cached task module and task class, raising if not loaded.

        Prefer the dedicated accessors ``_require_task_class()`` and
        ``_require_task_module_type()`` over indexing the returned tuple.

        Returns:
            Tuple containing the module and task class

        Raises:
            TaskModuleNotLoadedError: If load_task_module() has not been called
        """
        if self._task_module is None:
            raise TaskModuleNotLoadedError(
                f"Task module for flow '{self.name}' has not been loaded. "
                f"Call load_task_module() before accessing task-dependent methods."
            )
        return self._task_module

    def _require_task_class(self) -> type["DataFlowTask"]:
        """Return the loaded task class (raises if not loaded)."""
        return self._require_task_module()[1]

    def _require_task_module_type(self) -> ModuleType:
        """Return the loaded task module (raises if not loaded)."""
        return self._require_task_module()[0]

    def _check_task_module(
        self,
        namespace: str | None,
        entity_path: str | None,
        additional_task_paths: list[str] | None,
        additional_flow_task_types: dict[str, str] | None,
        errors: list[str],
    ) -> bool:
        """
        Check if the task module can be loaded.

        Args:
            namespace: The namespace of the data flow
            entity_path: The entity path from project
            additional_task_paths: Optional additional paths for module loading
            additional_flow_task_types: User-configured task type mappings
            errors: List to append error messages to

        Returns:
            True if task module is valid, False otherwise
        """
        try:
            self.resolve_task_module(
                namespace=namespace,
                entity_path=entity_path,
                additional_task_paths=additional_task_paths,
                additional_flow_task_types=additional_flow_task_types,
            )
            return True
        except Exception as exc:
            task_identifier = (
                self.task or self.task_type or f"auto-resolved for '{self.name}'"
            )
            errors.append(
                f"Task module '{task_identifier}' cannot be loaded:\n"
                f"{format_exception_chain(exception=exc)}"
            )
            return False

    def get_params_model_dict(
        self,
        additional_task_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get the parameters model dictionary."""
        if self.params is None:
            return {}
        return create_model_dict(
            execution_param_list=self.params,
            additional_paths=additional_task_paths,
        )

    def _check_params(
        self,
        errors: list[str],
        additional_task_paths: list[str] | None = None,
    ) -> None:
        """
        Check if static params can be instantiated correctly.

        Requires load_task_module() to have been called first.
        Static params are fully validated via create_model_dict().
        Runtime params are validated by the executor at execution time.

        Args:
            errors: List to append error messages to
            additional_task_paths: Optional list of additional paths for type import
        """
        if self.params is None:
            return

        try:
            task_class = self._require_task_class()
            combined_type_hints = {
                **task_class.get_init_param_type_hints(),
                **task_class.get_run_param_type_hints(),
            }
            create_model_dict(
                execution_param_list=self.params,
                additional_paths=additional_task_paths,
                param_type_hints=combined_type_hints,
            )
        except Exception as exc:
            errors.append(f"Params validation failed: {str(exc)}")

    def resolve_incremental_logic(
        self,
        task_class: type["DataFlowTask"] | None = None,
    ) -> FlowIncrementalLogic[Any]:
        """Return the incremental logic for this flow, with caching.

        Resolution priority (first match wins, result is cached):
          1. The strategy declared on ``self.incremental`` (per-flow YAML).
          2. The ``_INCREMENTAL_LOGIC`` ClassVar of the explicit ``task_class``
             argument when provided, else of the task class loaded via
             ``load_task_module()``.
          3. ``NO_INCREMENT_FLOW_INCREMENTAL_LOGIC`` as a safe default.

        Args:
            task_class: Optional task class to use as the source of the
                ClassVar fallback. When omitted, the loaded task module
                is required (call ``load_task_module()`` first).

        Returns:
            The resolved FlowIncrementalLogic for this flow.
        """
        if self._resolved_incremental_logic is not None:
            return self._resolved_incremental_logic

        from nld.flow.incremental.impl.no_increment.logic import (
            NO_INCREMENT_FLOW_INCREMENTAL_LOGIC,
        )
        from nld.flow.incremental.services.factory import IncrementalStateManagerFactory

        if self.incremental is not None:
            logic = IncrementalStateManagerFactory().get_incremental_logic(
                incremental_type=self.incremental.type,
            )
        else:
            if task_class is None:
                task_class = self._require_task_class()
            class_logic = task_class.get_class_incremental_logic()
            logic = (
                class_logic
                if class_logic is not None
                else NO_INCREMENT_FLOW_INCREMENTAL_LOGIC
            )

        self._resolved_incremental_logic = logic
        return logic

    def get_init_params_keys(self) -> list[str]:
        """
        Get the list of init parameter keys for this flow.

        Combines the task class's non-incremental init keys with the
        param keys of the flow-resolved incremental logic.

        Requires load_task_module() to have been called first.

        Returns:
            List of init parameter keys

        Raises:
            TaskModuleNotLoadedError: If load_task_module() has not been called
        """
        task_class = self._require_task_class()
        keys = list(task_class.get_init_params_keys())
        for param_def in self.resolve_incremental_logic().definition.param_definitions:
            if param_def.name not in keys:
                keys.append(param_def.name)
        return keys

    def get_params_model_dict_for_init(self) -> dict[str, Any]:
        """
        Get the parameters dictionary for init parameters.

        Requires load_task_module() to have been called first.

        Returns:
            Dictionary of init parameters with their values

        Raises:
            TaskModuleNotLoadedError: If load_task_module() has not been called
        """
        task_class = self._require_task_class()
        init_type_hints = task_class.get_init_param_type_hints()

        if self.params is None:
            return {}

        return {
            key: value
            for key, value in create_model_dict(
                execution_param_list=self.params,
                additional_paths=self._additional_task_paths,
                param_type_hints=init_type_hints,
            ).items()
            if key in self.get_init_params_keys()
        }

    def get_run_params_keys(self) -> list[str]:
        """
        Get the list of run parameter keys from the task class.

        Requires load_task_module() to have been called first.

        Returns:
            List of run parameter keys

        Raises:
            TaskModuleNotLoadedError: If load_task_module() has not been called
        """
        return self._require_task_class().get_run_params_keys()

    def get_params_model_dict_for_run(self) -> dict[str, Any]:
        """
        Get the parameters dictionary for run parameters.

        Requires load_task_module() to have been called first.

        Returns:
            Dictionary of run parameters with their values

        Raises:
            TaskModuleNotLoadedError: If load_task_module() has not been called
        """
        task_class = self._require_task_class()
        run_type_hints = task_class.get_run_param_type_hints()

        if self.params is None:
            return {}

        return {
            key: value
            for key, value in create_model_dict(
                execution_param_list=self.params,
                additional_paths=self._additional_task_paths,
                param_type_hints=run_type_hints,
            ).items()
            if key in self.get_run_params_keys()
        }


class NamespacedDataFlowDefinition(NldNamespacedBaseModelWrapper[DataFlowDefinition]):
    """DataFlowDefinition wrapped with namespace information."""
