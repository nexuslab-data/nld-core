from typing import TYPE_CHECKING

from nld.exceptions import ImplementationException
from nld.utils.import_utils import import_class_inside_module
from nld.utils.mixin import NldMixIn

# Intentional circular dependency: the transports package seeds this registry
# at import time, so the registry can only reference the transport base class
# for typing without importing it at runtime.
if TYPE_CHECKING:
    from nld.flow.alerting.models import FlowAlertTransportManifest
    from nld.flow.alerting.transports.base import FlowAlertTransport


class FlowAlertTransportRegistry(NldMixIn):
    """Registry of the alerting technologies a process can alert through.

    Holds one ``FlowAlertTransport`` *class* per name — instances are built
    per run from the environment — plus any external transport declared as
    an ``additional_alert_transports`` manifest in ``nld_project.yml`` that
    is still pending resolution. Built-in transports seed themselves when
    the ``nld.flow.alerting.transports`` package is first imported.

    A manifest's ``transport_class`` is only imported and validated the
    first time its name is looked up (``get`` / ``has``), mirroring
    ``DataQualityRuleRegistry``: loading a project must never require
    importing another project's Python code purely to inspect its metadata.
    ``names`` and ``is_pending`` answer without importing anything.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pending: dict[str, FlowAlertTransportManifest] = {}
        self._transports: dict[str, type[FlowAlertTransport]] = {}

    def register(self, transport_class: "type[FlowAlertTransport]") -> None:
        if not transport_class.name:
            raise ImplementationException(
                msg=(
                    f"Alert transport class '{transport_class.__name__}' "
                    f"declares no name and cannot be registered"
                ),
            )
        self._reject_if_claimed(name=transport_class.name)
        self._transports[transport_class.name] = transport_class

    def register_manifest(self, manifest: "FlowAlertTransportManifest") -> None:
        """Register an external transport declaratively, without importing it."""
        self._reject_if_claimed(name=manifest.name)
        self._pending[manifest.name] = manifest

    def _reject_if_claimed(self, name: str) -> None:
        if name in self._transports or name in self._pending:
            raise ImplementationException(
                msg=(
                    f"Alert transport '{name}' is already registered "
                    f"and cannot be overridden"
                ),
            )

    def unregister(self, name: str) -> None:
        """Remove a registered transport. Test isolation only."""
        self._pending.pop(name, None)
        self._transports.pop(name, None)

    def get(self, name: str) -> "type[FlowAlertTransport]":
        self._resolve_pending(name=name)
        if name not in self._transports:
            raise ImplementationException(
                msg=(
                    f"Alert transport '{name}' is not available; "
                    f"known transports: {self.names()}"
                ),
            )
        return self._transports[name]

    def has(self, name: str) -> bool:
        self._resolve_pending(name=name)
        return name in self._transports

    def is_pending(self, name: str) -> bool:
        """Whether the name is a declared manifest not imported yet."""
        return name in self._pending

    def names(self) -> list[str]:
        return sorted({*self._transports.keys(), *self._pending.keys()})

    def _resolve_pending(self, name: str) -> None:
        """Import and validate a pending external transport.

        No-op once resolved (or if ``name`` was never registered). Left
        pending on failure, so a broken declaration keeps failing loudly on
        every subsequent lookup rather than silently caching a bad state.
        """
        manifest = self._pending.get(name)
        if manifest is None:
            return
        from nld.flow.alerting.transports.base import FlowAlertTransport
        from nld.project.project_exceptions import NldProjectError

        _, resolved_class = import_class_inside_module(manifest.transport_class)
        if not (
            isinstance(resolved_class, type)
            and issubclass(resolved_class, FlowAlertTransport)
        ):
            raise NldProjectError(
                f"transport_class '{manifest.transport_class}' resolved to "
                f"'{resolved_class.__name__}' which is not a subclass "
                f"of FlowAlertTransport"
            )
        if resolved_class.name != manifest.name:
            raise NldProjectError(
                f"Additional alert transport '{manifest.name}' resolved to a "
                f"transport named '{resolved_class.name}'; the manifest name "
                f"and the transport name must match"
            )
        del self._pending[name]
        self._transports[name] = resolved_class


_REGISTRY_SINGLETON: FlowAlertTransportRegistry | None = None


def get_flow_alert_transport_registry() -> FlowAlertTransportRegistry:
    """Return the process-wide registry singleton."""
    global _REGISTRY_SINGLETON
    if _REGISTRY_SINGLETON is None:
        _REGISTRY_SINGLETON = FlowAlertTransportRegistry()
    return _REGISTRY_SINGLETON
