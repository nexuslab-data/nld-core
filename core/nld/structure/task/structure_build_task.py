from typing import Any

from nld.project import Project
from nld.service.nld_entity_registry import NldEntityRegistry
from nld.structure.service.structure_builder import StructureBuilder
from nld.task import BaseRunStatus, ExecutionInfo, StandardTask


class StructureBuildTask(StandardTask):
    init_params = ["project", "exc_info", "output_in_project", "output_csv"]
    run_params = ["structure", "adapter"]

    def __init__(
        self,
        project: Project,
        exc_info: ExecutionInfo,
        output_in_project: bool,
        output_csv: bool,
        **kwargs: Any,
    ) -> None:
        super().__init__(exc_info=exc_info, **kwargs)
        self.project = project
        self.exc_info = exc_info
        self.output_in_project = output_in_project
        self.output_csv = output_csv

    def run(  # type: ignore[override]
        self,
        structure: str,
        adapter: str,
        output_folder_name: str | None = None,
        *args: str,
        **kwargs: str,
    ) -> bool:
        run_status = BaseRunStatus.SUCCESS.value
        self.log_info("Build structure executing")

        nld_entity_registry: NldEntityRegistry = self.project.entity_registry

        try:
            builder = StructureBuilder(
                structure=nld_entity_registry.get_structure(structure).model,
                structure_adapter=nld_entity_registry.get_structure_adapter(
                    adapter
                ).model,
                output_folder_name=(
                    output_folder_name
                    if not self.output_in_project
                    else self.project.root_folder_path
                ),
            )
            builder.build()

        except Exception as e:
            self.log_error(f"Structure building failed: {e}")
            raise

        return run_status
