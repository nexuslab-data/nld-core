from typing import TYPE_CHECKING

from nld.exceptions import ImplementationException
from nld.utils.import_utils import import_class_inside_module
from nld.utils.mixin import NldMixIn

# Intentional circular dependency: the rules package seeds this registry
# at import time, so the registry can only reference the rule base class
# for typing without importing it at runtime.
if TYPE_CHECKING:
    from nld.flow.quality.models import DataQualityRuleManifest
    from nld.flow.quality.rules.base import DataQualityRule


class DataQualityRuleRegistry(NldMixIn):
    """Registry of available data quality rules.

    Holds one `DataQualityRule` instance per resolved rule name, plus any
    external rule declared as an `additional_quality_rules` manifest in
    `nld_project.yml` that is still pending resolution. Built-in rules seed
    themselves (already resolved) when the `nld.flow.quality.rules` package
    is first imported.

    A manifest's `rule_class` is only imported, instantiated and validated
    the first time its rule name is actually looked up (`get`/`has`) — see
    `_resolve_pending`. This mirrors `FlowIncrementalTypeRegistry`: loading a
    project must never require importing another project's Python code
    purely to inspect its declared metadata (e.g. a cross-project catalog
    tool that only needs scheduling entities, not flow execution).
    """

    def __init__(self) -> None:
        super().__init__()
        self._rules: dict[str, DataQualityRule] = {}
        self._pending: dict[str, DataQualityRuleManifest] = {}

    def register(self, rule: "DataQualityRule") -> None:
        if not rule.name:
            raise ImplementationException(
                msg=(
                    f"Data quality rule class '{type(rule).__name__}' "
                    f"declares no name and cannot be registered"
                )
            )
        self._reject_if_claimed(name=rule.name)
        self._rules[rule.name] = rule

    def register_manifest(self, manifest: "DataQualityRuleManifest") -> None:
        """Register an external rule declaratively, without importing it yet.

        The manifest's `rule_class` is resolved lazily on first lookup — see
        the class docstring.
        """
        self._reject_if_claimed(name=manifest.name)
        self._pending[manifest.name] = manifest

    def _reject_if_claimed(self, name: str) -> None:
        if name in self._rules or name in self._pending:
            raise ImplementationException(
                msg=(
                    f"Data quality rule '{name}' is already registered "
                    f"and cannot be overridden"
                )
            )

    def unregister(self, name: str) -> None:
        """Remove a previously registered data quality rule.

        Provided for test isolation; production code should never call this.
        """
        self._rules.pop(name, None)
        self._pending.pop(name, None)

    def get(self, name: str) -> "DataQualityRule":
        self._resolve_pending(name=name)
        if name not in self._rules:
            raise ImplementationException(
                msg=f"Data quality rule '{name}' is not available"
            )
        return self._rules[name]

    def has(self, name: str) -> bool:
        self._resolve_pending(name=name)
        return name in self._rules

    def names(self) -> list[str]:
        return sorted({*self._rules.keys(), *self._pending.keys()})

    def _resolve_pending(self, name: str) -> None:
        """Import, validate and instantiate a pending external rule.

        No-op once resolved (or if `name` was never registered at all). Left
        pending on failure, so a broken declaration keeps failing loudly on
        every subsequent lookup rather than silently caching a bad state.
        """
        manifest = self._pending.get(name)
        if manifest is None:
            return
        from nld.flow.quality.rules.base import DataQualityRule
        from nld.project.project_exceptions import NldProjectError

        _, resolved_class = import_class_inside_module(manifest.rule_class)
        if not (
            isinstance(resolved_class, type)
            and issubclass(resolved_class, DataQualityRule)
        ):
            raise NldProjectError(
                f"rule_class '{manifest.rule_class}' resolved to "
                f"'{resolved_class.__name__}' which is not a subclass "
                f"of DataQualityRule"
            )
        rule = resolved_class()
        if rule.name != manifest.name:
            raise NldProjectError(
                f"Additional data quality rule '{manifest.name}' resolved "
                f"to a rule named '{rule.name}'; the manifest name and the "
                f"rule name must match"
            )
        del self._pending[name]
        self._rules[name] = rule


_REGISTRY_SINGLETON: DataQualityRuleRegistry | None = None


def get_data_quality_rule_registry() -> DataQualityRuleRegistry:
    """Return the process-wide registry singleton."""
    global _REGISTRY_SINGLETON
    if _REGISTRY_SINGLETON is None:
        _REGISTRY_SINGLETON = DataQualityRuleRegistry()
    return _REGISTRY_SINGLETON
