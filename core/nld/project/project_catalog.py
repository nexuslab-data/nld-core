import os
from typing import Any

from pydantic import Field as PydanticField
from pydantic import field_validator, model_validator

from nld.pydantic import NldBaseModel, NldNamedBaseModel
from nld.utils.yaml_util import load_yaml_file_into_dict

NLD_PROJECT_CATALOG_FILENAME = "nld_project_catalog.yml"


class NldProjectCatalogEntry(NldNamedBaseModel):
    """A single nld project catalogued within a multi-project platform.

    ``path`` locates the project root (the folder holding ``nld_project.yml``)
    relative to the catalog file. ``predecessors`` names the other catalogued
    projects this one depends on, which together form the cross-project
    dependency graph (e.g. a business project runs after the acquisition
    projects that feed it).
    """

    path: str = PydanticField(
        description="Project root path relative to the catalog file, pointing "
        "at the folder holding nld_project.yml",
    )
    predecessors: list[str] = PydanticField(
        default_factory=list,
        description="Names of catalogued projects this project depends on",
    )


class NldProjectCatalog(NldBaseModel):
    """Catalog of the nld projects making up a data platform.

    Cross-project concept that sits above individual projects: it records every
    project, where it lives on disk, and the dependency links between them. The
    ``projects`` mapping is keyed by project name, mirroring how the source YAML
    keys each project; ``_inject_name`` folds each key into the entry's ``name``
    field before validation.

    Example:
        >>> catalog = NldProjectCatalog.from_yaml("ops/scheduling")
        >>> catalog.get_entry("clh_business_dwh").predecessors
        ['clh_acquisition_opendata', 'clh_acquisition_web_hr']
    """

    projects_base_path: str | None = PydanticField(
        default=None,
        description="Base directory, relative to this catalog file, against which "
        "each entry's `path` is resolved. When unset, paths resolve relative to "
        "the catalog file's own directory.",
    )
    projects: dict[str, NldProjectCatalogEntry] = PydanticField(
        default_factory=dict,
        description="Catalogued projects indexed by project name",
    )

    @model_validator(mode="before")
    @classmethod
    def _inject_project_names(cls, data: Any) -> Any:
        """Fold each project mapping's key into the entry's ``name`` field."""
        if not isinstance(data, dict):
            return data
        raw_projects = data.get("projects")
        if not isinstance(raw_projects, dict):
            return data
        named_projects = {
            name: cls._inject_name(name=name, body=body)
            for name, body in raw_projects.items()
        }
        return {**data, "projects": named_projects}

    @staticmethod
    def _inject_name(name: str, body: Any) -> Any:
        """Fold the mapping key into the entry body as its ``name`` field."""
        flattened = dict(body) if isinstance(body, dict) else {}
        flattened.setdefault("name", name)
        return flattened

    @field_validator("projects")
    @classmethod
    def _validate_predecessors_exist(
        cls,
        projects: dict[str, NldProjectCatalogEntry],
    ) -> dict[str, NldProjectCatalogEntry]:
        """Ensure every declared predecessor is itself a catalogued project."""
        for name, entry in projects.items():
            unknown = [
                predecessor
                for predecessor in entry.predecessors
                if predecessor not in projects
            ]
            if unknown:
                raise ValueError(
                    f"Project '{name}' references unknown predecessors: "
                    f"{', '.join(unknown)}",
                )
        return projects

    @classmethod
    def from_yaml(cls, root_path: str) -> "NldProjectCatalog":
        """Load the catalog from ``nld_project_catalog.yml`` in a folder."""
        catalog_path = os.path.join(
            os.path.normpath(root_path),
            NLD_PROJECT_CATALOG_FILENAME,
        )
        return cls.from_dict(load_yaml_file_into_dict(catalog_path))

    @property
    def entry_names(self) -> list[str]:
        """Names of every catalogued project, in declaration order."""
        return list(self.projects.keys())

    def get_entry(self, name: str) -> NldProjectCatalogEntry | None:
        """Return the catalogued project with this name, or None if absent."""
        return self.projects.get(name)

    def predecessors_of(self, name: str) -> list[str]:
        """Return the predecessor names declared for this project."""
        entry = self.get_entry(name)
        return list(entry.predecessors) if entry is not None else []
