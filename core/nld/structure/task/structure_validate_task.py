import json
import sys
from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.service import EntityTypeNames
from nld.structure.field import CharacterisationValidationFinding
from nld.structure.service import StructureCharacterisationChecker
from nld.task.base import StandardTask


class StructureValidateTask(StandardTask):
    """Validate field characterisation pertinence for structures.

    For each structure, builds a StructureCharacterisationChecker over the
    effective catalogue (the built-in defaults merged with project-declared
    definitions visible from the structure's namespace) and checks every field
    characterisation against it: the characterisation must be a known
    definition, its attributes must be allowed, and a single-field-only
    definition must appear on at most one field. Validates a single structure
    when ``name`` is given, otherwise every structure visible from
    ``namespace``.

    Renders a human-friendly summary by default; ``display_format="json"`` emits
    the full machine-readable payload to stdout instead. Raises when at least
    one structure is invalid, so the command exits non-zero.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(name="name", mandatory=False),
        ExecutionParameterDefinition(name="namespace", mandatory=False),
        ExecutionParameterDefinition(name="display_format", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        name: str | None = None,
        namespace: str | None = None,
        display_format: str = "text",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.name = name
        self.namespace = namespace
        self.display_format = display_format
        self.execution_context.load_entities(
            entity_types=[
                EntityTypeNames.STRUCTURE,
                EntityTypeNames.FIELD_CHARACTERISATION_DEFINITION,
            ],
        )

    def run(self, **kwargs: Any) -> bool:
        registry = self.execution_context.entity_registry

        if self.name is not None:
            wrappers = [
                registry.get_structure(
                    entity_key=self.name,
                    namespace=self.namespace,
                )
            ]
        else:
            structure_dict = registry.get_structure_dict(namespace=self.namespace)
            wrappers = [structure_dict[key] for key in sorted(structure_dict.keys())]

        checker_cache: dict[str, StructureCharacterisationChecker] = {}
        results: list[dict[str, Any]] = []
        for wrapper in wrappers:
            namespace = str(wrapper.namespace)
            if namespace not in checker_cache:
                checker_cache[namespace] = (
                    StructureCharacterisationChecker.from_registry(
                        registry=registry,
                        namespace=namespace,
                    )
                )
            findings = checker_cache[namespace].check(
                structure=wrapper.model,
            )
            results.append(
                {
                    "structure": wrapper.id,
                    "findings": findings,
                }
            )

        if self.display_format == "json":
            self._emit_json(results)
        else:
            self._render(results)

        total_errors = sum(len(entry["findings"]) for entry in results)
        if total_errors:
            raise ValueError(
                f"Structure characterisation validation failed with "
                f"{total_errors} error(s)",
            )
        return True

    def _emit_json(self, results: list[dict[str, Any]]) -> None:
        payload = [
            {
                "structure": entry["structure"],
                "findings": [finding.model_dump() for finding in entry["findings"]],
            }
            for entry in results
        ]
        sys.stdout.write(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        )
        sys.stdout.flush()

    def _render(self, results: list[dict[str, Any]]) -> None:
        self.log_info("Validating field characterisations:")
        self.log_separator_line()
        if not results:
            self.log_info("  No structures found")
            self.log_separator_line()
            return
        failed = 0
        for entry in results:
            findings: list[CharacterisationValidationFinding] = entry["findings"]
            if not findings:
                self.log_info(f"  OK    {entry['structure']}")
                continue
            failed += 1
            self.log_error(
                f"  FAIL  {entry['structure']} ({len(findings)} finding(s))",
            )
            for finding in findings:
                self.log_error(
                    f"          - {finding.render_line()}",
                )
        self.log_separator_line()
        if failed:
            self.log_info(f"{failed} of {len(results)} structure(s) failed validation")
        else:
            self.log_info(f"All {len(results)} structure(s) are valid")
        self.log_separator_line()
