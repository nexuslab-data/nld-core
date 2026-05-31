from typing import Any

from nld.project import Project
from nld.service import NldEntityRegistry
from nld.structure.service.sql_renderer_wrapper import (
    SQLRenderEntry,
    SQLRendererWrapper,
)
from nld.task import BaseRunStatus, ExecutionInfo, StandardTask


class StructureSqlRendererTask(StandardTask):
    init_params = [
        "project",
        "exc_info",
    ]
    run_params = ["structure", "renderer", "output_folder_name", "params"]

    def __init__(
        self, project: Project, exc_info: ExecutionInfo, **kwargs: Any
    ) -> None:
        super().__init__(exc_info=exc_info, **kwargs)
        self.project = project

    def run(  # type: ignore[override]
        self,
        structure: str,
        renderer: str,
        output_folder_name: str,
        params: dict[str, Any] | None = None,
    ) -> bool:
        run_status = BaseRunStatus.SUCCESS.value
        params = params if params is not None else {}
        self.log_info("SQL rendering executing")

        # load structure object
        nld_entity_registry: NldEntityRegistry = self.project.entity_registry
        current_structure = nld_entity_registry.get_structure(structure)
        if current_structure is None:
            raise ValueError(f"Structure not found: {structure}")

        # load renderer wrapper
        renderer_wrapper = nld_entity_registry.get_sql_renderer(renderer)  # type: ignore[attr-defined]

        if renderer_wrapper is None and renderer.endswith(".sql"):
            renderer_wrapper = SQLRendererWrapper(
                name=structure,
                renderer=[SQLRenderEntry(name=renderer)],
            )
        if not renderer_wrapper:
            raise ValueError(f"Renderer not found: {renderer}")

        templates_dict = nld_entity_registry.get_sql_template_dict()  # type: ignore[attr-defined]
        adapters_dict = nld_entity_registry.get_structure_adapter_dict()

        try:
            renderer_wrapper.render_all(
                structure=current_structure,
                params=params,
                output_folder=output_folder_name,
                templates_dict=templates_dict,
                adapters_dict=adapters_dict,
            )
        except Exception as e:
            self.log_error(f"Structure rendering failed: {e}")
            raise

        self.log_info("SQL rendering done")
        return run_status
