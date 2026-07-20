import os
from pathlib import Path
from typing import Any

from nld.project import NldProjectCatalog, Project
from nld.task.context.context import NldExecutionContext
from nld.task.context.request import TaskRequest
from nld.task.context.variables import (
    CONFIG_FOLDER_PATH,
    ROOT_FOLDER_PATH,
)

DEFAULT_EXTERNAL_EXECUTION_NAME = "external_service"


def init_execution_context(
    config_folder_path: str | None = None,
    root_folder_path: str | None = None,
    entity_types: list[str] | None = None,
    execution_name: str = DEFAULT_EXTERNAL_EXECUTION_NAME,
    with_project: bool = True,
    load_entities: bool = True,
    extra_params: dict[str, Any] | None = None,
) -> NldExecutionContext:
    """Initialize a ready-to-use NldExecutionContext for an external service.

    External services (schedulers, generators, custom tooling) only need to
    read project assets through the entity registry, so the verbose
    TaskRequest plumbing is collapsed into a single call here. The returned
    context is already set as the current context and, unless disabled, has its
    project entities loaded so the entity registry can be used immediately.

    Args:
        config_folder_path: Path used to resolve connection configs. Falls back
            to the ``NLD__CONFIG_FOLDER_PATH`` env var then ``./.nld`` when None.
        root_folder_path: Path to the project root holding ``nld_project.yml``.
            Falls back to the ``NLD__ROOT_FOLDER_PATH`` env var then the current
            working directory when None.
        entity_types: Entity types to load into the registry. When None every
            entity type is loaded. Ignored when ``load_entities`` is False.
        execution_name: Name attached to the execution for logging and state.
        with_project: Whether to load ``nld_project.yml`` on initialization.
        load_entities: Whether to populate the entity registry before
            returning. Requires ``with_project`` to be True.
        extra_params: Additional task parameters merged into the request, for
            callers needing parameters beyond the two standard folder paths.

    Returns:
        An NldExecutionContext set as the current context, with entities loaded
        when requested.

    Example:
        >>> context = init_execution_context(
        ...     root_folder_path="/path/to/project",
        ...     entity_types=["data_flow_definition", "scheduling"],
        ... )
        >>> schedulings = context.entity_registry.get_flow_scheduling_dict()
    """
    params: dict[str, Any] = dict(extra_params) if extra_params is not None else {}
    if config_folder_path is not None:
        params[CONFIG_FOLDER_PATH] = config_folder_path
    if root_folder_path is not None:
        params[ROOT_FOLDER_PATH] = root_folder_path

    task_request = TaskRequest(
        execution_name=execution_name,
        params=params,
    )
    context = NldExecutionContext(
        task_request=task_request,
        with_project=with_project,
    )
    context.set_current()

    if load_entities and with_project:
        context.load_entities(entity_types=entity_types)

    return context


def load_project(
    root_folder_path: str | Path,
    *,
    entity_types: list[str] | None = None,
    config_folder_path: str | Path | None = None,
) -> Project:
    """Load a single nld ``Project`` from a project root.

    Thin convenience over :func:`init_execution_context` for callers that only
    want the loaded project (schedulers, generators, tooling). ``config_folder_path``
    falls back to ``root_folder_path`` when not given.

    Args:
        root_folder_path: Path to the project root holding ``nld_project.yml``.
        entity_types: Entity types to load into the registry. When None every
            entity type is loaded.
        config_folder_path: Path used to resolve connection configs. Defaults to
            ``root_folder_path`` when None.

    Returns:
        The loaded ``Project``.
    """
    return init_execution_context(
        root_folder_path=str(root_folder_path),
        config_folder_path=str(config_folder_path or root_folder_path),
        entity_types=entity_types,
    ).project


def load_catalog_projects(
    catalog_dir: str | Path,
    *,
    entity_types: list[str] | None = None,
    config_folder_path: str | Path | None = None,
) -> dict[str, Project]:
    """Load every project listed in an nld project catalog.

    Reads ``nld_project_catalog.yml`` from ``catalog_dir`` (the nld-core
    :class:`~nld.project.NldProjectCatalog` model) and loads each catalogued
    project via :func:`load_project`. Returns the loaded projects keyed by
    catalog name, in declaration order.

    Path resolution: each entry's ``path`` is resolved against the catalog's
    ``projects_base_path`` (itself relative to ``catalog_dir``) when set,
    otherwise against ``catalog_dir`` (the catalog file's own directory).

    Note: like :func:`init_execution_context`, each load sets the loaded context
    as the current context, so afterwards the current context is the last
    project's. Intended for read-only multi-project access through the returned
    projects' entity registries.

    Args:
        catalog_dir: Directory holding ``nld_project_catalog.yml``.
        entity_types: Entity types to load into each project's registry. When
            None every entity type is loaded.
        config_folder_path: Path used to resolve connection configs for every
            project. Defaults to each project's own root when None.

    Returns:
        The loaded projects keyed by catalog name, in declaration order.

    Raises:
        NldMissingProjectYamlFile: If a catalogued project has no
            ``nld_project.yml`` at its resolved root, raised by the underlying
            project loading.
    """
    catalog = NldProjectCatalog.from_yaml(str(catalog_dir))
    base = Path(catalog_dir)
    if catalog.projects_base_path is not None:
        base = base / catalog.projects_base_path
    projects: dict[str, Project] = {}
    for name, entry in catalog.projects.items():
        root = Path(os.path.normpath(base / entry.path))
        projects[name] = load_project(
            root,
            entity_types=entity_types,
            config_folder_path=config_folder_path,
        )
    return projects
