import os

from nld.pydantic.base_model import NldBaseModel
from nld.pydantic.namespace import NldNamespace
from pydantic import field_validator

# Flow companion files (SQL queries, Python tasks) live in the flows folder.
FLOWS_FOLDER_NAME = "flows"
# Seed CSV files are stored with the entities without being an entity type.
SEEDS_FOLDER_NAME = "seeds"


class NldEntityLayout(NldBaseModel):
    """Where the entity files of a project live on disk.

    By default entities are stored type first, the namespace being the path
    below the entity folder: ``flows/source/raw/flow.yml`` holds flow ``flow``
    of namespace ``source.raw``. A namespace declared as a namespace folder
    groups its entities by namespace instead, the namespace being the folder
    namespace extended by the path below the entity folder:
    ``source/flows/raw/flow.yml`` holds the same flow when ``source`` is a
    namespace folder. Both forms resolve to the same namespaces, so moving a
    namespace into its folder is a pure file move.

    Every namespace is owned by exactly one location: the deepest declared
    folder containing it, or the type-first tree when no folder contains it.
    That ownership is what keeps each path lookup (SQL files, seeds, Python
    flow modules, written entities) deterministic.

    Attributes:
        entity_path: Entities root folder, relative to the project root.
        folder_namespaces: Namespaces stored as namespace folders, sorted.
    """

    entity_path: str = "."
    folder_namespaces: list[str] = []

    @field_validator("folder_namespaces")
    @classmethod
    def normalize_folder_namespaces(cls, value: list[str]) -> list[str]:
        """Normalize, deduplicate and sort the declared namespace folders."""
        return sorted({str(NldNamespace(namespace)) for namespace in value})

    def get_owning_folder_namespace(self, namespace: str) -> NldNamespace | None:
        """Return the deepest namespace folder containing ``namespace``.

        Returns None when no declared folder contains it, meaning that the
        namespace is stored in the type-first tree.
        """
        owning_folders = [
            NldNamespace(folder_namespace)
            for folder_namespace in self.folder_namespaces
            if NldNamespace(folder_namespace).contains(namespace)
        ]
        if not owning_folders:
            return None
        return max(
            owning_folders,
            key=lambda folder_namespace: folder_namespace.depth,
        )

    def get_entity_relative_directory(
        self,
        entity_folder_name: str,
        namespace: str,
    ) -> str:
        """Return the directory of a namespace, relative to the entities root.

        Example:
            With ``source`` declared as a namespace folder, the ``flows``
            directory of namespace ``source.raw`` is ``source/flows/raw``,
            while the one of namespace ``other.raw`` is ``flows/other/raw``.
        """
        target_namespace = NldNamespace(namespace)
        folder_namespace = self.get_owning_folder_namespace(
            namespace=target_namespace,
        )
        if folder_namespace is None:
            path_parts = [entity_folder_name, target_namespace.to_path()]
        else:
            path_parts = [
                folder_namespace.to_path(),
                entity_folder_name,
                target_namespace.relative_to(ancestor=folder_namespace).to_path(),
            ]
        return os.path.join(*[part for part in path_parts if part])

    def get_entity_directory(
        self,
        entities_root_folder_path: str,
        entity_folder_name: str,
        namespace: str,
    ) -> str:
        """Return the absolute directory of a namespace for an entity folder."""
        return os.path.join(
            entities_root_folder_path,
            self.get_entity_relative_directory(
                entity_folder_name=entity_folder_name,
                namespace=namespace,
            ),
        )

    def get_entity_folder_roots(
        self,
        entities_root_folder_path: str,
        entity_folder_name: str,
    ) -> list[tuple[str, NldNamespace | None]]:
        """List every directory where entities of an entity folder may live.

        The type-first directory comes first, paired with None, then one
        directory per namespace folder, paired with the folder namespace.
        Parent folders come before their children, so a namespace is always
        loaded after the namespaces it may inherit from.
        """
        folder_roots: list[tuple[str, NldNamespace | None]] = [
            (
                os.path.join(
                    entities_root_folder_path,
                    entity_folder_name,
                ),
                None,
            ),
        ]
        sorted_folder_namespaces = sorted(
            (
                NldNamespace(folder_namespace)
                for folder_namespace in self.folder_namespaces
            ),
            key=lambda folder_namespace: (folder_namespace.depth, folder_namespace),
        )
        for folder_namespace in sorted_folder_namespaces:
            folder_roots.append(
                (
                    os.path.join(
                        entities_root_folder_path,
                        folder_namespace.to_path(),
                        entity_folder_name,
                    ),
                    folder_namespace,
                ),
            )
        return folder_roots

    def get_module_path(
        self,
        entity_folder_name: str,
        namespace: str,
        module_name: str,
    ) -> str:
        """Return the Python module path of a file stored with the entities.

        Example:
            With ``entity_path: assets`` and ``source`` declared as a
            namespace folder, the module of flow ``load`` in namespace
            ``source.raw`` is ``assets.source.flows.raw.load``.
        """
        relative_directory = self.get_entity_relative_directory(
            entity_folder_name=entity_folder_name,
            namespace=namespace,
        )
        path_parts = [
            *self._get_entity_path_parts(),
            *relative_directory.split(os.sep),
            module_name,
        ]
        return ".".join(path_parts)

    def find_entity_location(
        self,
        relative_file_path: str,
        entity_folder_names: list[str],
    ) -> tuple[str, NldNamespace] | None:
        """Find the entity folder and namespace a file is stored under.

        The path is relative to the entities root. The deepest namespace
        folder prefixing the path wins; otherwise the path is read type first.

        Returns:
            The entity folder name and the namespace of the file, or None
            when the file is not stored under any of ``entity_folder_names``.

        Example:
            With ``source`` declared as a namespace folder,
            ``source/flows/raw/load.yml`` is located in ``("flows",
            "source.raw")`` and ``flows/other/load.yml`` in ``("flows",
            "other")``.
        """
        directory_parts = [
            part
            for part in os.path.dirname(os.path.normpath(relative_file_path)).split(
                os.sep,
            )
            if part
        ]
        sorted_folder_namespaces = sorted(
            (
                NldNamespace(folder_namespace)
                for folder_namespace in self.folder_namespaces
            ),
            key=lambda folder_namespace: folder_namespace.depth,
            reverse=True,
        )
        for folder_namespace in sorted_folder_namespaces:
            folder_parts = folder_namespace.split(".")
            if directory_parts[: len(folder_parts)] != folder_parts:
                continue
            location = self._match_entity_folder(
                directory_parts=directory_parts[len(folder_parts) :],
                entity_folder_names=entity_folder_names,
                base_namespace=folder_namespace,
            )
            if location is not None:
                return location
        return self._match_entity_folder(
            directory_parts=directory_parts,
            entity_folder_names=entity_folder_names,
            base_namespace=NldNamespace(NldNamespace.ROOT_VALUE),
        )

    def _get_entity_path_parts(self) -> list[str]:
        """Split the entity path into Python module segments."""
        normalized_entity_path = os.path.normpath(self.entity_path)
        if normalized_entity_path == os.curdir:
            return []
        return [
            part
            for part in normalized_entity_path.replace("\\", "/").split("/")
            if part
        ]

    @staticmethod
    def _match_entity_folder(
        directory_parts: list[str],
        entity_folder_names: list[str],
        base_namespace: NldNamespace,
    ) -> tuple[str, NldNamespace] | None:
        """Match the longest entity folder name prefixing the directory parts."""
        sorted_entity_folder_names = sorted(
            entity_folder_names,
            key=lambda entity_folder_name: len(entity_folder_name.split("/")),
            reverse=True,
        )
        for entity_folder_name in sorted_entity_folder_names:
            entity_folder_parts = entity_folder_name.split("/")
            if directory_parts[: len(entity_folder_parts)] != entity_folder_parts:
                continue
            relative_namespace = NldNamespace.from_path(
                "/".join(directory_parts[len(entity_folder_parts) :]),
            )
            return entity_folder_name, base_namespace.append(relative_namespace)
        return None
