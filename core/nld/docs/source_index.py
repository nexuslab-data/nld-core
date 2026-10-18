import os
import re
from typing import Any

import yaml

from nld.pydantic import NldBaseModel, NldEntityLayout, NldNamespace
from nld.service import EntityDefinition
from nld.utils.file_util import get_files_grouped_by_subdirectory
from nld.utils.yaml_util import YAML_FILE_STANDARD_REGEX

MARKDOWN_FILE_STANDARD_REGEX: str = r".*\.md$"

NAMESPACE_DOCUMENTATION_FILE_NAME: str = "_namespace.md"


def _entity_folder_roots(
    root_directory: str,
    entity_folder_name: str,
    entity_layout: NldEntityLayout | None,
) -> list[tuple[str, NldNamespace | None]]:
    """Every existing directory an entity folder may live in.

    Delegates to the project's own layout so the docs read exactly the
    directories the registry loaded from, type-first tree and namespace
    folders alike.
    """
    layout = entity_layout if entity_layout is not None else NldEntityLayout()
    return [
        (folder_path, folder_namespace)
        for folder_path, folder_namespace in layout.get_entity_folder_roots(
            entities_root_folder_path=root_directory,
            entity_folder_name=entity_folder_name,
        )
        if os.path.isdir(folder_path)
    ]


def _join_namespace(
    folder_namespace: NldNamespace | None,
    relative_namespace: str,
) -> str:
    """Prefix a namespace relative to a folder root with that folder."""
    base = (
        folder_namespace
        if folder_namespace is not None
        else NldNamespace(NldNamespace.ROOT_VALUE)
    )
    return str(base.append(relative_namespace))


class EntitySourceFile(NldBaseModel):
    """One entity YAML file found on disk, with its raw text."""

    entity_type: str
    name: str
    namespace: str
    path: str
    text: str


def _read_entity_name(
    file_path: str,
    parsed: Any,
) -> str:
    """Return the declared entity name, falling back to the file stem."""
    if isinstance(parsed, dict):
        declared = parsed.get("name")
        if isinstance(declared, str) and declared:
            return declared
    return os.path.splitext(os.path.basename(file_path))[0]


class EntitySourceIndex:
    """Index of the entity files of a project, keyed by type, namespace, name.

    The registry keeps loaded models but not the file they came from, and the
    docs UI needs both the source path (to link back to the repository) and the
    raw YAML (to show the asset as it was written).
    """

    def __init__(self) -> None:
        self._files: dict[tuple[str, str, str], EntitySourceFile] = {}

    def index_entity_definition(
        self,
        root_directory: str,
        entity_definition: EntityDefinition,
        entity_layout: NldEntityLayout | None = None,
    ) -> None:
        """Index every YAML file of one entity type under one root.

        The walk follows the project's entity layout, so a namespace kept in
        its own folder (``assets/web_hr/structure/…``) is indexed alongside
        the type-first tree (``assets/structure/web_hr/…``). Without this the
        source path, the source YAML and the ``<entity>.md`` sidecars would
        all come back empty for a namespace-folder project.
        """
        if entity_definition.file_format != "yaml":
            return

        for folder_path, folder_namespace in _entity_folder_roots(
            root_directory=root_directory,
            entity_folder_name=entity_definition.folder_name,
            entity_layout=entity_layout,
        ):
            files_by_namespace = get_files_grouped_by_subdirectory(
                root_path=folder_path,
                pattern=YAML_FILE_STANDARD_REGEX,
            )
            for relative_namespace, file_paths in files_by_namespace.items():
                namespace = _join_namespace(
                    folder_namespace=folder_namespace,
                    relative_namespace=relative_namespace,
                )
                for file_path in file_paths:
                    self._index_file(
                        entity_type=entity_definition.name,
                        namespace=namespace,
                        file_path=file_path,
                    )

    def _index_file(
        self,
        entity_type: str,
        namespace: str,
        file_path: str,
    ) -> None:
        """Read one entity file and record it under its declared name."""
        try:
            with open(file_path, encoding="utf-8") as file_handle:
                text = file_handle.read()
        except OSError:
            return

        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError:
            parsed = None

        name = _read_entity_name(
            file_path=file_path,
            parsed=parsed,
        )
        # The grouping helper keys on the on-disk folder ("." at the root,
        # "/"-separated below); the registry keys on the dotted namespace.
        # Normalising here keeps both lookups on the same key.
        namespace_key = str(NldNamespace.from_path(namespace))
        self._files[(entity_type, namespace_key, name)] = EntitySourceFile(
            entity_type=entity_type,
            name=name,
            namespace=namespace_key,
            path=file_path,
            text=text,
        )

    def get(
        self,
        entity_type: str,
        namespace: str,
        name: str,
    ) -> EntitySourceFile | None:
        """Return the source file of one entity, when it was found."""
        return self._files.get((entity_type, str(NldNamespace(namespace)), name))

    def relative_path(
        self,
        source_file: EntitySourceFile,
        root_directory: str,
    ) -> str:
        """Return the source path relative to the project root when possible."""
        try:
            return os.path.relpath(source_file.path, root_directory)
        except ValueError:
            return source_file.path


def find_markdown_sidecar(
    source_file: EntitySourceFile | None,
) -> tuple[str, str] | None:
    """Return the ``<entity>.md`` sitting next to an entity file, if any.

    This is the documentation convention the docs UI reads today: dropping a
    markdown file next to an asset documents it, with no YAML edit at all.
    """
    if source_file is None:
        return None

    markdown_path = f"{os.path.splitext(source_file.path)[0]}.md"
    if not os.path.isfile(markdown_path):
        return None

    try:
        with open(markdown_path, encoding="utf-8") as file_handle:
            return markdown_path, file_handle.read()
    except OSError:
        return None


def find_namespace_documentation(
    root_directory: str,
    entity_definitions: list[EntityDefinition],
    entity_layout: NldEntityLayout | None = None,
) -> dict[str, tuple[str, str]]:
    """Collect the ``_namespace.md`` files of every entity folder.

    Returns a mapping of namespace to ``(path, markdown)``. A namespace
    documented in several entity folders keeps the first file found, in
    entity-definition order, which makes the result deterministic.
    """
    compiled_pattern = re.compile(MARKDOWN_FILE_STANDARD_REGEX)
    collected: dict[str, tuple[str, str]] = {}

    for entity_definition in entity_definitions:
        for folder_path, folder_namespace in _entity_folder_roots(
            root_directory=root_directory,
            entity_folder_name=entity_definition.folder_name,
            entity_layout=entity_layout,
        ):
            files_by_namespace = get_files_grouped_by_subdirectory(
                root_path=folder_path,
                pattern=compiled_pattern.pattern,
            )
            for relative_namespace, file_paths in files_by_namespace.items():
                for file_path in file_paths:
                    if os.path.basename(file_path) != NAMESPACE_DOCUMENTATION_FILE_NAME:
                        continue
                    namespace_key = _join_namespace(
                        folder_namespace=folder_namespace,
                        relative_namespace=relative_namespace,
                    )
                    if namespace_key in collected:
                        continue
                    try:
                        with open(file_path, encoding="utf-8") as file_handle:
                            collected[namespace_key] = (
                                file_path,
                                file_handle.read(),
                            )
                    except OSError:
                        continue

    return collected
