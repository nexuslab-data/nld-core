from __future__ import annotations

from typing import Any

from nld.connector.base.connector import SQLDataConnector
from nld.structure.deploy.structure_metadata_backend_manager import (
    StructureMetadataBackendManager,
)
from nld.structure.deploy.structure_metadata_models import StructureMetadataRow
from nld.structure.structure.structure import Structure


class DeploySnapshot:
    """The cached live state of one (connector, schema) deploy target.

    Owns the three caches a deploy run consults instead of re-querying
    per structure — the live structures (keyed by the connector's full
    object path), the recorded metadata state rows (keyed by
    ``(namespace, structure_name)``) and the schema's view-dependency
    graph — together with their write-through and invalidation rules.

    Built once per (connector, schema) per run and shared by every
    deploy manager targeting that pair, so planning and applying read
    the same state and post-DDL updates are visible to every later
    structure in the run. A cache miss falls back to a live,
    single-object read — memoized so a caller that skipped
    ``prefetch`` still gets correct, if unbatched, behavior.
    """

    def __init__(
        self,
        connector: SQLDataConnector[Any],
        deploy_schema: str,
        metadata_manager: StructureMetadataBackendManager | None = None,
        metadata_schema: str | None = None,
    ) -> None:
        self._reader = connector.get_structure_reader()
        self._deploy_schema = deploy_schema
        self._metadata_manager = metadata_manager
        self._metadata_schema = metadata_schema
        self._live_structures: dict[str, Structure | None] = {}
        self._state_rows: dict[tuple[str, str], StructureMetadataRow | None] = {}
        self._dependent_views_graph: dict[str, list[str]] | None = None

    def prefetch(self) -> None:
        """Read the whole target once: live structures and state rows.

        One schema-wide read replaces the per-structure round trips
        every later consultation would otherwise pay (worst case on
        Snowflake: ~4 reader round trips per structure).
        """
        self._live_structures = dict(
            self._reader.extract_all_structures(schema=self._deploy_schema),
        )
        if self._metadata_manager is not None and self._metadata_schema is not None:
            self._state_rows = dict(
                self._metadata_manager.read_all_state_rows(
                    metadata_schema=self._metadata_schema,
                ),
            )

    # ------------------------------------------------------------------
    # Live structures
    # ------------------------------------------------------------------

    def object_key(self, table_name: str) -> str:
        """Cache key of a live object: the connector's full object path.

        Bare names would let two same-named tables in different
        schemas overwrite each other whenever a prefetch spans more
        than one schema.
        """
        return self._reader.build_full_object_path(
            schema=self._deploy_schema,
            object_name=table_name,
        )

    def read_table(self, table_name: str) -> Structure | None:
        """Read a live table by physical name, consulting the cache."""
        cache_key = self.object_key(table_name=table_name)
        if cache_key not in self._live_structures:
            live_structures = self._reader.extract_structures(
                schema=self._deploy_schema,
                object_name=table_name,
            )
            self._live_structures[cache_key] = (
                live_structures[0] if live_structures else None
            )
        return self._live_structures[cache_key]

    def set_live_structure(self, structure: Structure) -> None:
        """Write a just-deployed structure through to the cache."""
        self._live_structures[self.object_key(table_name=structure.name)] = structure

    def forget_live_object(self, table_name: str) -> None:
        """Drop a physical name from the cache (e.g. freed by a rename)."""
        self._live_structures.pop(self.object_key(table_name=table_name), None)

    # ------------------------------------------------------------------
    # Metadata state rows
    # ------------------------------------------------------------------

    def get_state_row(
        self,
        namespace: str,
        structure_name: str,
    ) -> StructureMetadataRow | None:
        """Read the recorded state row of a structure, consulting the cache."""
        if self._metadata_manager is None or self._metadata_schema is None:
            raise ValueError(
                "DeploySnapshot has no metadata backend configured — "
                "state rows cannot be read.",
            )
        key = (namespace, structure_name)
        if key not in self._state_rows:
            self._state_rows[key] = self._metadata_manager.read_state_row(
                metadata_schema=self._metadata_schema,
                structure_name=structure_name,
                namespace=namespace,
            )
        return self._state_rows[key]

    def set_state_row(
        self,
        namespace: str,
        structure_name: str,
        row: StructureMetadataRow | None,
    ) -> None:
        """Write a just-recorded state row through to the cache."""
        self._state_rows[(namespace, structure_name)] = row

    def forget_state_row(
        self,
        namespace: str,
        structure_name: str,
    ) -> None:
        """Drop a state row from the cache (e.g. soft-deleted by a rename)."""
        self._state_rows.pop((namespace, structure_name), None)

    # ------------------------------------------------------------------
    # Dependent views
    # ------------------------------------------------------------------

    def dependent_views_graph(self) -> dict[str, list[str]]:
        """Return the schema's view-dependency graph, fetched once per run."""
        if self._dependent_views_graph is None:
            self._dependent_views_graph = self._reader.get_all_dependent_views(
                schema=self._deploy_schema,
            )
        return self._dependent_views_graph
