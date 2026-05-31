from nld.flow.incremental.models import FlowIncrementalTypeManifest
from nld.flow.incremental.services.registry import (
    get_flow_incremental_type_registry,
)

BUILTIN_INCREMENTAL_TYPE_MANIFESTS: list[FlowIncrementalTypeManifest] = [
    FlowIncrementalTypeManifest(
        name="by_key",
        logic_module="nld.flow.incremental.impl.by_key.logic",
        state_manager_module="nld.flow.incremental.impl.by_key.manager",
        backend_package="nld.flow.incremental.impl.by_key.backend",
    ),
    FlowIncrementalTypeManifest(
        name="by_source_tst",
        logic_module="nld.flow.incremental.impl.by_source_tst.logic",
        state_manager_module="nld.flow.incremental.impl.by_source_tst.manager",
        backend_package="nld.flow.incremental.impl.by_source_tst.backend",
    ),
    FlowIncrementalTypeManifest(
        name="no_increment",
        logic_module="nld.flow.incremental.impl.no_increment.logic",
        state_manager_module="nld.flow.incremental.impl.no_increment.manager",
        backend_package="nld.flow.incremental.impl.no_increment.backend",
    ),
]


def _register_builtins() -> None:
    registry = get_flow_incremental_type_registry()
    for manifest in BUILTIN_INCREMENTAL_TYPE_MANIFESTS:
        if not registry.has(name=manifest.name):
            registry.register(manifest=manifest)


_register_builtins()

__all__ = [
    "BUILTIN_INCREMENTAL_TYPE_MANIFESTS",
]
