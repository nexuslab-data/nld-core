from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.service import EntityTypeNames
from nld.task.base import StandardTask


class StructureModelListTask(StandardTask):
    """List the structure models visible from a namespace.

    Walks the entity registry (with the structure-model search direction) and
    prints each model with its namespace and link count.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(name="namespace", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.namespace = namespace
        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.STRUCTURE_MODEL]
        )

    def run(self, **kwargs: Any) -> bool:
        registry = self.execution_context.entity_registry
        keys = registry.get_structure_model_keys(namespace=self.namespace)

        self.log_info("Structure Models:")
        self.log_separator_line()
        if not keys:
            self.log_info("  No structure models found")
            self.log_separator_line()
            return True

        rows: list[tuple[str, ...]] = []
        for key in keys:
            namespaced = registry.get_structure_model(
                entity_key=key,
                namespace=self.namespace,
            )
            model = namespaced.model
            rows.append(
                (
                    key,
                    str(namespaced.namespace),
                    str(len(model.links)),
                    ", ".join(model.get_link_names()),
                )
            )

        self.log_aligned_table(
            headers=["Name", "Namespace", "Links", "Link names"],
            rows=[list(row) for row in rows],
        )
        self.log_separator_line()
        return True
