import importlib
import inspect

from nld.flow.definition import DataFlowDefinition
from nld.flow.definition.sql_config import SQLConfig
from nld.flow.sql.sql_rendering import SQLRendering
from nld.flow.sql.transformation.base import SQLRenderingTransformation
from nld.flow.sql.transformation.base_resolver import TransformationResolver
from nld.flow.sql.transformation.deduplicated_select import DeduplicatedSelectResolver
from nld.flow.sql.transformation.select import SelectResolver
from nld.flow.sql.transformation.select.transformation import SelectRendering
from nld.logging.logger import log_debug_default

RESOLVERS: dict[str, TransformationResolver] = {
    "DEDUPLICATED_SELECT": DeduplicatedSelectResolver(),
    "SELECT": SelectResolver(),
}

_project_resolvers: dict[str, TransformationResolver] = {}

_project_resolvers_loaded: bool = False


def get_rendering_transformation(
    name: str,
    config: SQLConfig | None = None,
    connector_type: str | None = None,
) -> SQLRenderingTransformation:
    """Resolve a rendering transformation by name (case-insensitive).

    Resolution priority:
    1. Connector-specific override (via the active resolver)
    2. Project-level resolver (overrides builtin for same name)
    3. Builtin resolver
    """
    upper_name = name.upper()
    _ensure_project_resolvers_loaded()

    resolver = _project_resolvers.get(upper_name) or RESOLVERS.get(upper_name)
    if resolver is None:
        available = sorted(set(RESOLVERS) | set(_project_resolvers))
        raise ValueError(
            f"Unknown rendering transformation: '{name}'. Available: {available}"
        )

    if connector_type is not None:
        override_cls = resolver.find_connector_override(
            connector_type=connector_type,
        )
        if override_cls is not None:
            return override_cls(config=config)

    return resolver.create_builtin(config=config)


def resolve_rendering(
    flow_definition: DataFlowDefinition,
) -> SQLRendering:
    """Resolve the rendering strategy from flow definition config."""
    if (
        flow_definition.sql is not None
        and flow_definition.sql.transformation is not None
    ):
        connector_type = _resolve_connector_type(
            flow_definition=flow_definition,
        )
        return get_rendering_transformation(
            flow_definition.sql.transformation,
            config=flow_definition.sql,
            connector_type=connector_type,
        )
    return SelectRendering()


def _resolve_connector_type(
    flow_definition: DataFlowDefinition,
) -> str | None:
    """Extract the connector type from the target structure if available."""
    if flow_definition.target_structure is None:
        return None
    target_structure = flow_definition.resolve_target_structure()
    return target_structure.connector_type


def _ensure_project_resolvers_loaded() -> None:
    """Lazily discover project-level resolvers from NldExecutionContext.

    Scans modules configured in sql_transformations python additional
    paths for TransformationResolver subclasses and registers them.
    """
    global _project_resolvers_loaded
    if _project_resolvers_loaded:
        return

    _project_resolvers_loaded = True

    try:
        from nld.task.context import NldExecutionContext

        context = NldExecutionContext.get_current()
        if context is None:
            return
        paths = context.project.sql_transformations_python_additional_paths
    except Exception:
        return

    for module_path in paths:
        try:
            module = importlib.import_module(module_path)
            log_debug_default(
                f"Loaded project transformation module: {module_path}",
            )
        except ModuleNotFoundError:
            log_debug_default(
                f"No project transformation module found at {module_path}",
            )
            continue

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, TransformationResolver)
                and attr is not TransformationResolver
                and inspect.getmodule(attr) is module
            ):
                instance = attr()
                resolver_name = instance.transformation_name.upper()
                _project_resolvers[resolver_name] = instance
                log_debug_default(
                    f"Registered project resolver: {resolver_name}",
                )


def _reset_registries() -> None:
    """Reset mutable state for test isolation."""
    global _project_resolvers_loaded
    _project_resolvers.clear()
    _project_resolvers_loaded = False
