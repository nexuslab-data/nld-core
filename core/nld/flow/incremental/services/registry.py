from nld.exceptions import ImplementationException
from nld.flow.incremental.models import FlowIncrementalTypeManifest
from nld.utils.mixin import NldMixIn


class FlowIncrementalTypeRegistry(NldMixIn):
    """Registry of available incremental types.

    Holds one `FlowIncrementalTypeManifest` per incremental type name. Built-in
    types seed themselves when their package is first imported; external types
    are added through `AdditionalIncrementalTypeConfig` declared in
    `nld_project.yml` and registered on project load.
    """

    def __init__(self) -> None:
        super().__init__()
        self._manifests: dict[str, FlowIncrementalTypeManifest] = {}

    def register(self, manifest: FlowIncrementalTypeManifest) -> None:
        if manifest.name in self._manifests:
            raise ImplementationException(
                msg=(
                    f"Incremental type '{manifest.name}' is already registered "
                    f"and cannot be overridden"
                )
            )
        self._manifests[manifest.name] = manifest

    def unregister(self, name: str) -> None:
        """Remove a previously registered incremental type.

        Provided for test isolation; production code should never call this.
        """
        self._manifests.pop(name, None)

    def get(self, name: str) -> FlowIncrementalTypeManifest:
        if name not in self._manifests:
            raise ImplementationException(
                msg=f"Incremental type '{name}' is not available"
            )
        return self._manifests[name]

    def has(self, name: str) -> bool:
        return name in self._manifests

    def names(self) -> list[str]:
        return sorted(self._manifests.keys())


_REGISTRY_SINGLETON: FlowIncrementalTypeRegistry | None = None


def get_flow_incremental_type_registry() -> FlowIncrementalTypeRegistry:
    """Return the process-wide registry singleton."""
    global _REGISTRY_SINGLETON
    if _REGISTRY_SINGLETON is None:
        _REGISTRY_SINGLETON = FlowIncrementalTypeRegistry()
    return _REGISTRY_SINGLETON
