from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.task.base import StandardTask


class StructureAdaptTask(StandardTask):
    """Task that adapts a structure using a structure adapter.

    Loads a structure and adapter from the entity registry, runs the
    adaptation, and writes the resulting structure as YAML.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        "adapter_name",
        "structure_name",
        ExecutionParameterDefinition(
            name="structure_namespace",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        adapter_name: str,
        structure_name: str,
        structure_namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self.execution_context.load_entities()

        namespaced_adapter = (
            self.execution_context.entity_registry.get_structure_adapter(
                entity_key=adapter_name,
            )
        )
        namespaced_structure = self.execution_context.entity_registry.get_structure(
            entity_key=structure_name,
            namespace=structure_namespace,
        )

        self._file_output_service = self.execution_context.file_output_service
        self.structure = namespaced_structure.model
        self.structure_adapter = namespaced_adapter.model
        self.structure_namespace = structure_namespace

    def run(self, **kwargs: Any) -> bool:
        """Adapt the structure and write the result as YAML."""
        adapted_structure = self.structure_adapter.adapt_structure(
            original_structure=self.structure,
            namespace=self.structure_namespace,
        )

        self._file_output_service.write_yaml_file(
            nld_base_model=adapted_structure,
            internal_folder_name="structure",
            namespace=self.structure_namespace,
        )

        self.log_info(
            f"Adapted structure '{adapted_structure.name}' written successfully",
        )
        return True
