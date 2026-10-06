from typing import Any, ClassVar

from nld.flow.definition import NamespacedDataFlowDefinition
from nld.flow.structure_generation.structure_generator import (
    StructureGenerationResult,
    TargetStructureGenerator,
    split_entity_id,
)
from nld.parameters import ExecutionParameterDefinition
from nld.pydantic import NldNamespace
from nld.service import EntityTypeNames, NldEntityRegistry
from nld.structure import NamespacedStructure
from nld.task.base import StandardTask


class StructureGenerateTask(StandardTask):
    """Generate or regenerate flow target structures from their predecessor.

    With ``name``, generates the target structure of that flow, creating
    the structure file when it does not exist yet. Without ``name``,
    regenerates every structure already generated (holding a
    ``generation_metadata`` block) whose flow is visible from ``namespace``.

    With ``check``, writes nothing: prints the diff of every structure that
    a generation would change and fails when at least one is stale, so the
    command can guard CI and pre-commit hooks.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="check",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="name",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="namespace",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        check: bool = False,
        name: str | None = None,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.check = check
        self.name = name
        self.namespace = namespace
        self.execution_context.load_entities(
            entity_types=[
                EntityTypeNames.DATA_FLOW_DEFINITION,
                EntityTypeNames.STRUCTURE,
                EntityTypeNames.STRUCTURE_TEMPLATE,
            ],
        )
        project = self.execution_context.project
        self.generator = TargetStructureGenerator(
            entities_root_folder_path=project.entities_root_folder_path,
            entity_layout=project.entity_layout,
            entity_registry=self.execution_context.entity_registry,
        )

    def run(self, **kwargs: Any) -> bool:
        """Generate the selected structures, or check them with ``check``."""
        flows = self._select_flows()
        if not flows:
            self.log_info("No generated structure found for the given parameters")
            return True

        failures: list[str] = []
        stale_structure_ids: list[str] = []
        for namespaced_flow in flows:
            try:
                result = self.generator.generate(namespaced_flow=namespaced_flow)
            except Exception as error:
                self.log_error(f"FAIL   {namespaced_flow.id}: {error}")
                failures.append(namespaced_flow.id)
                continue

            for warning in result.warnings:
                self.log_warn(f"       {result.structure_id}: {warning}")
            if self.check:
                if not result.is_up_to_date():
                    stale_structure_ids.append(result.structure_id)
                    self._log_check_result(result=result)
                else:
                    self.log_info(f"OK     {result.structure_id}")
                continue
            self._write_result(result=result)

        self.log_separator_line()
        if failures:
            raise ValueError(
                f"Structure generation failed for {len(failures)} flow(s): "
                f"{', '.join(failures)}"
            )
        if stale_structure_ids:
            raise ValueError(
                f"{len(stale_structure_ids)} generated structure(s) are stale: "
                f"{', '.join(stale_structure_ids)}. "
                f"Run 'nld structure generate' to regenerate them"
            )
        self.log_info(f"{len(flows)} structure(s) processed")
        return True

    def _select_flows(self) -> list[NamespacedDataFlowDefinition]:
        """Select the flow to generate, or the flows of generated structures."""
        registry: NldEntityRegistry = self.execution_context.entity_registry
        if self.name is not None:
            return [
                registry.get_data_flow_definition(
                    entity_key=self.name,
                    namespace=self.namespace,
                ),
            ]

        flows: dict[str, NamespacedDataFlowDefinition] = {}
        for namespaced_structure in self._list_generated_structures(registry):
            generation_metadata = namespaced_structure.model.generation_metadata
            assert generation_metadata is not None
            flow_namespace, flow_name = split_entity_id(
                entity_id=generation_metadata.flow,
            )
            if self.namespace is not None and not NldNamespace(
                flow_namespace,
            ).is_related_to(NldNamespace(self.namespace)):
                continue
            try:
                namespaced_flow = registry.get_data_flow_definition(
                    entity_key=flow_name,
                    namespace=flow_namespace,
                )
            except Exception as error:
                self.log_warn(
                    f"Skipping '{namespaced_structure.id}': its flow "
                    f"'{generation_metadata.flow}' cannot be found ({error})"
                )
                continue
            flows[namespaced_flow.id] = namespaced_flow
        return [flows[flow_id] for flow_id in sorted(flows)]

    @staticmethod
    def _list_generated_structures(
        registry: NldEntityRegistry,
    ) -> list[NamespacedStructure]:
        """List every generated structure, across all namespaces."""
        structures_by_namespace = registry.get_all_entity_dict().get(
            EntityTypeNames.STRUCTURE,
            {},
        )
        generated_structures: list[NamespacedStructure] = []
        for namespace, structures in structures_by_namespace.items():
            for structure in structures.values():
                if structure.is_generated():
                    generated_structures.append(
                        NamespacedStructure(
                            model=structure,
                            namespace=namespace,
                        ),
                    )
        return generated_structures

    def _write_result(self, result: StructureGenerationResult) -> None:
        """Write one generated structure and log what changed."""
        is_new = result.is_new()
        if not self.generator.write(result=result):
            self.log_info(f"OK     {result.structure_id} is up to date")
            return
        action = "CREATE" if is_new else "UPDATE"
        self.log_info(f"{action} {result.structure_id} -> {result.file_path}")
        for change in result.changes:
            self.log_info(f"         - {change}")

    def _log_check_result(self, result: StructureGenerationResult) -> None:
        """Log why a structure is stale, with the diff a generation would apply."""
        state = "MISSING" if result.is_new() else "STALE"
        self.log_warn(f"{state}  {result.structure_id} ({result.file_path})")
        for change in result.changes:
            self.log_warn(f"         - {change}")
        diff = result.render_diff()
        if diff:
            self.log_info(diff.rstrip("\n"))
