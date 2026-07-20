from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.service import EntityTypeNames
from nld.task.base import StandardTask


class StructureModelValidateTask(StandardTask):
    """Validate structure models against the structures they reference.

    Runs each model's field-mapping validation (every mapped left/right field
    must exist in the resolved left/right structure). Validates a single model
    when ``name`` is given, otherwise every model visible from ``namespace``.

    Raises when at least one model is invalid, so the command exits non-zero.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(name="name", mandatory=False),
        ExecutionParameterDefinition(name="namespace", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        name: str | None = None,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.name = name
        self.namespace = namespace
        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.STRUCTURE_MODEL]
        )

    def run(self, **kwargs: Any) -> bool:
        registry = self.execution_context.entity_registry

        if self.name is not None:
            keys = [self.name]
        else:
            keys = registry.get_structure_model_keys(namespace=self.namespace)

        self.log_info("Validating structure models:")
        self.log_separator_line()

        if not keys:
            self.log_info("  No structure models found")
            self.log_separator_line()
            return True

        total_errors = 0
        for key in keys:
            namespaced = registry.get_structure_model(
                entity_key=key,
                namespace=self.namespace,
            )
            findings = namespaced.model.validate_mappings()
            if not findings:
                self.log_info(f"  OK    {key}")
                continue
            total_errors += len(findings)
            self.log_error(f"  FAIL  {key} ({len(findings)} finding(s))")
            for finding in findings:
                self.log_error(f"          - {finding.render_line()}")

        self.log_separator_line()

        if total_errors:
            raise ValueError(
                f"Structure model validation failed with {total_errors} error(s)",
            )

        self.log_info(f"All {len(keys)} structure model(s) are valid")
        return True
