from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.service import EntityTypeNames, FileOutputService
from nld.structure.audit import render_audit_to_markdown
from nld.task.base import StandardTask

AUDIT_OUTPUT_FOLDER_NAME = "audits"


class StructureAuditRenderTask(StandardTask):
    """Render a structure audit to a standard markdown report.

    Reproduces the data held in the audit YAML (target, metadata, per-column
    coverage and distributions) as markdown. By default the report is written
    through the :class:`FileOutputService` to a timestamped folder under
    ``output/`` (never inside the project); ``override_output_folder_path``
    redirects it to a chosen folder and ``stdout`` prints it instead of writing
    a file. This is a generated view and never overwrites the curated analysis
    markdown kept beside the audit.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        "name",
        ExecutionParameterDefinition(name="namespace", mandatory=False),
        ExecutionParameterDefinition(
            name="override_output_folder_path",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="stdout",
            mandatory=False,
            data_type="bool",
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        name: str,
        namespace: str | None = None,
        override_output_folder_path: str | None = None,
        stdout: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.namespace = namespace
        self.override_output_folder_path = override_output_folder_path
        self.stdout = stdout
        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.STRUCTURE_AUDIT],
            namespace=namespace,
        )
        namespaced = self.execution_context.entity_registry.get_structure_audit(
            entity_key=name,
            namespace=namespace,
        )
        self.model = namespaced.model

    def run(self, **kwargs: Any) -> bool:
        markdown = render_audit_to_markdown(self.model)

        if self.stdout:
            self.log_info(markdown)
            return True

        file_name = f"{self.model.name}.md"
        file_output_service = FileOutputService(
            root_folder_path=self.execution_context.get_nld_root_folder_path(),
            override_output_folder_path=self.override_output_folder_path,
            entity_layout=self.execution_context.entity_layout,
        )
        file_output_service.write_file(
            file_name=file_name,
            content=markdown,
            internal_folder_name=AUDIT_OUTPUT_FOLDER_NAME,
            namespace=self.namespace,
        )
        output_path = file_output_service.resolve_output_file_path(
            file_name=file_name,
            internal_folder_name=AUDIT_OUTPUT_FOLDER_NAME,
            namespace=self.namespace,
        )
        self.log_info(f"Rendered audit '{self.model.name}' to {output_path}")
        return True
