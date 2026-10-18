import os

from nld.docs.models import DocsDocumentationBlock
from nld.docs.source_index import (
    EntitySourceFile,
    EntitySourceIndex,
    find_markdown_sidecar,
    find_namespace_documentation,
)
from nld.pydantic import NldEntityLayout
from nld.service import EntityDefinition

PROJECT_DOCUMENTATION_FILE_NAMES: tuple[str, ...] = (
    "README.md",
    "PROJECT.md",
)


def relative_to_root(
    path: str,
    root_folder_path: str,
) -> str:
    """Return a path relative to the project root, or unchanged when impossible.

    The snapshot must not depend on where the project was checked out, so
    every path it carries is relative to the project root.
    """
    try:
        return os.path.relpath(path, root_folder_path)
    except ValueError:
        return path


class DocumentationCollector:
    """Collects the markdown that documents a project and its assets.

    Documentation is read from the filesystem next to the assets it describes:
    ``<entity>.md`` for one asset, ``_namespace.md`` for a namespace and the
    project README for the project itself. Nothing has to be declared in the
    YAML for an asset to become documented.
    """

    def __init__(
        self,
        source_index: EntitySourceIndex,
        root_folder_path: str,
    ) -> None:
        self.source_index = source_index
        self.root_folder_path = root_folder_path
        self._namespace_documentation: dict[str, tuple[str, str]] = {}

    def collect_namespace_documentation(
        self,
        root_directories: list[str],
        entity_definitions: list[EntityDefinition],
        entity_layout: NldEntityLayout | None = None,
    ) -> None:
        """Read the ``_namespace.md`` files of every entity folder."""
        for root_directory in root_directories:
            found = find_namespace_documentation(
                root_directory=root_directory,
                entity_definitions=entity_definitions,
                entity_layout=entity_layout,
            )
            for namespace, block in found.items():
                self._namespace_documentation.setdefault(namespace, block)

    def documented_namespaces(self) -> list[str]:
        """Return the namespaces that carry a documentation file."""
        return sorted(self._namespace_documentation)

    def namespace_documentation(
        self,
        namespace: str,
    ) -> list[DocsDocumentationBlock]:
        """Return the documentation blocks of one namespace."""
        block = self._namespace_documentation.get(namespace)
        if block is None:
            return []
        path, content = block
        return [self._block(path=path, content=content)]

    def entity_documentation(
        self,
        source_file: EntitySourceFile | None,
    ) -> list[DocsDocumentationBlock]:
        """Return the documentation blocks of one asset."""
        sidecar = find_markdown_sidecar(source_file=source_file)
        if sidecar is None:
            return []
        path, content = sidecar
        return [self._block(path=path, content=content)]

    def project_documentation(self) -> list[DocsDocumentationBlock]:
        """Return the project-level documentation, from its README."""
        for file_name in PROJECT_DOCUMENTATION_FILE_NAMES:
            candidate = os.path.join(self.root_folder_path, file_name)
            if not os.path.isfile(candidate):
                continue
            try:
                with open(candidate, encoding="utf-8") as file_handle:
                    content = file_handle.read()
            except OSError:
                continue
            return [self._block(path=candidate, content=content)]
        return []

    def _block(
        self,
        path: str,
        content: str,
    ) -> DocsDocumentationBlock:
        """Build a block whose path is relative to the project root."""
        return DocsDocumentationBlock(
            title=None,
            content=content,
            source_path=relative_to_root(
                path=path,
                root_folder_path=self.root_folder_path,
            ),
        )
