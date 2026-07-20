from typing import Any

from nld.project.project_catalog import NldProjectCatalog
from nld.task import BaseRunStatus, StandardTask


class ProjectCatalogInfoTask(StandardTask):
    """Displays the nld project catalog: projects and their predecessor links."""

    init_params = ["root_folder_path"]

    def __init__(
        self,
        root_folder_path: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.root_folder_path = root_folder_path

    def run(self, **kwargs: Any) -> bool:
        """Display the catalogued projects without loading the projects themselves."""
        run_status = BaseRunStatus.SUCCESS.value

        catalog = NldProjectCatalog.from_yaml(self.root_folder_path)
        self._display_catalog(catalog=catalog)

        return run_status

    def _display_catalog(self, catalog: NldProjectCatalog) -> None:
        """Render the catalog as a table of projects and their predecessor links."""
        base_path = catalog.projects_base_path or "."
        self.log_section_header(
            "Project Catalog",
            f"Projects base path: {base_path}",
        )
        self.log_empty_line()

        if not catalog.projects:
            self.log_info("Project catalog is empty: no projects declared.")
            return

        self.log_info(f"Projects: {len(catalog.projects)}")
        self.log_separator_line()
        self.log_aligned_table(
            headers=["Project", "Path", "Predecessors"],
            rows=[
                [
                    entry.name,
                    entry.path,
                    ", ".join(entry.predecessors) if entry.predecessors else "-",
                ]
                for entry in catalog.projects.values()
            ],
        )
        self.log_separator_line()
