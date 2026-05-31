from typing import Any

from nld.parameters.execution_params_def import (
    ExecutionParameterDefinition,
)
from nld.task import BaseRunStatus, StandardTask


class ProjectEntityInfoTask(StandardTask):
    """Displays information about entities for a specific entity type."""

    init_params = [
        "entity_type",
        ExecutionParameterDefinition(name="namespace", mandatory=False),
    ]

    def __init__(
        self,
        entity_type: str,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.entity_type = entity_type
        self.namespace = namespace

    def run(self, **kwargs: Any) -> bool:
        """Display entity information for the specified entity type."""
        run_status = BaseRunStatus.SUCCESS.value

        self.execution_context.load_entities()
        registry = self.execution_context.entity_registry

        self._display_entity_info(registry=registry)

        return run_status

    def _display_entity_info(self, registry: Any) -> None:
        """Display entity information for the specified entity type."""
        self.log_info("=" * 60)
        self.log_info(f"Entity Type: {self.entity_type}")
        if self.namespace:
            self.log_info(f"Namespace: {self.namespace}")
        self.log_info("=" * 60)
        self.log_info("")

        namespaces = registry.get_entity_type_namespaces(entity_type=self.entity_type)

        if self.namespace:
            namespaces = [
                ns
                for ns in namespaces
                if ns == self.namespace or ns.startswith(f"{self.namespace}.")
            ]

        if not namespaces:
            self.log_info(f"No entities found for entity type: {self.entity_type}")
            self.log_info("=" * 60)
            return

        self.log_info("Namespaces and Entity Counts:")
        self.log_info("-" * 60)

        total_count = 0
        for namespace in namespaces:
            entity_keys = registry.get_entity_keys(
                entity_type=self.entity_type,
                namespace=namespace,
                include_children=False,
            )
            count = len(entity_keys)
            total_count += count
            self._display_namespace_count(namespace=namespace, count=count)

        self.log_info("-" * 60)
        self.log_info(f"Total Distinct Keys: {total_count}")
        self.log_info("-" * 60)

    def _display_namespace_count(self, namespace: str, count: int) -> None:
        """Display formatted count for a namespace."""
        self.log_info(f"  {namespace:<40} : {count:>5}")
