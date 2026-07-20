from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nld.connector.base.connector import SQLDataConnector
from nld.structure.deploy import structure_deploy_manager
from nld.structure.deploy.deploy_snapshot import DeploySnapshot
from nld.structure.deploy.structure_deploy_manager import StructureDeployManager
from nld.structure.deploy.structure_metadata_backend_manager import (
    StructureMetadataBackendManager,
)


class StructureDeployTargetFactory:
    """Builds and caches one deploy manager per (connection, schema) target.

    One factory is created per deploy run and handed to every step of
    it — planning and applying — so all steps share the same managers,
    and through them the same prefetched ``DeploySnapshot`` and backup
    suffix. This is what makes a run's metadata reads O(schemas)
    instead of O(structures): without the shared factory each step
    rebuilt a fresh, cache-less manager per structure.

    ``metadata_connector``/``metadata_schema`` pin the metadata
    backend for every target (the flow-deploy model); when omitted,
    each target defaults to its own connector and schema (the
    structure-deploy model for projects without a configured backend).
    """

    def __init__(
        self,
        connector_resolver: Callable[[str], SQLDataConnector[Any]],
        metadata_connector: SQLDataConnector[Any] | None = None,
        metadata_schema: str | None = None,
        variables: dict[str, str] | None = None,
    ) -> None:
        self._connector_resolver = connector_resolver
        self._metadata_connector = metadata_connector
        self._metadata_schema = metadata_schema
        self._variables = variables or {}
        # Module-qualified call: tests freeze the mint through the
        # manager module, and the factory must honor the same patch
        # point.
        self._backup_suffix = structure_deploy_manager.mint_backup_suffix()
        self._managers: dict[tuple[str, str], StructureDeployManager] = {}

    def get_manager(
        self,
        connection_name: str,
        schema_name: str,
    ) -> StructureDeployManager:
        """Return the target's deploy manager, building it on first use.

        The first request for a (connection, schema) pair opens the
        connector, ensures the metadata tables and prefetches the
        target's live structures and state rows in one schema-wide
        read; every later request reuses that manager and its caches.
        """
        manager_key = (connection_name, schema_name)
        manager = self._managers.get(manager_key)
        if manager is not None:
            return manager

        sql_connector = self._connector_resolver(connection_name)
        metadata_connector = self._metadata_connector or sql_connector
        metadata_schema = self._metadata_schema or schema_name
        metadata_manager = StructureMetadataBackendManager(
            metadata_connector=metadata_connector,
        )
        metadata_manager.ensure_metadata_tables(
            metadata_schema=metadata_schema,
        )

        snapshot = DeploySnapshot(
            connector=sql_connector,
            deploy_schema=schema_name,
            metadata_manager=metadata_manager,
            metadata_schema=metadata_schema,
        )
        snapshot.prefetch()

        manager = StructureDeployManager(
            structure_connector=sql_connector,
            deploy_schema=schema_name,
            metadata_backend_connector=metadata_connector,
            metadata_schema=metadata_schema,
            variables=self._variables,
            snapshot=snapshot,
            backup_suffix=self._backup_suffix,
        )
        self._managers[manager_key] = manager
        return manager
