from __future__ import annotations

from nld.deploy.change_file_models import RenameStructureDirective
from nld.structure.deploy.deploy_snapshot import DeploySnapshot
from nld.structure.deploy.structure_diff import StructureDiff
from nld.structure.deploy.structure_diff_ddl_statement_builder import DDLStatement
from nld.structure.deploy.structure_metadata_backend_manager import (
    StructureMetadataBackendManager,
)
from nld.structure.deploy.structure_metadata_models import StructureMetadataRow
from nld.structure.deploy.structure_schema_history import (
    StructureSchemaHistoryRecord,
    StructureSchemaSnapshot,
    build_structure_snapshot_json,
)
from nld.structure.structure.structure import NamespacedStructure


class MetadataRecorder:
    """Records deployment outcomes on the metadata backend.

    Owns the identity chain (stable ``uid`` carried across declared
    renames) and the history/state writes, keeping the snapshot's
    state-row cache authoritative after every write.
    """

    def __init__(
        self,
        metadata_manager: StructureMetadataBackendManager,
        metadata_schema: str,
        deploy_schema: str,
        snapshot: DeploySnapshot,
    ) -> None:
        self._metadata_manager = metadata_manager
        self._metadata_schema = metadata_schema
        self._deploy_schema = deploy_schema
        self._snapshot = snapshot

    def resolve_backend_identity(
        self,
        namespace: str,
        structure_name: str,
        pending_structure_renames: list[RenameStructureDirective],
    ) -> tuple[str | None, str | None]:
        """Resolve the stable uid and previous deployment id of a structure.

        A declared table rename carries the identity of the old-name
        record forward and soft-deletes it, so the asset history stays
        continuous across renames. With no previous record the uid is
        minted fresh by the history record builder.
        """
        previous_row = self._snapshot.get_state_row(
            namespace=namespace,
            structure_name=structure_name,
        )
        if previous_row is not None:
            return previous_row.uid, previous_row.deployment_id

        for directive in pending_structure_renames:
            old_namespace, _, old_name = directive.from_name.rpartition(".")
            old_row = self._snapshot.get_state_row(
                namespace=old_namespace or ".",
                structure_name=old_name,
            )
            if old_row is None:
                continue
            self._metadata_manager.soft_delete_structure(
                metadata_schema=self._metadata_schema,
                structure_name=old_name,
                namespace=old_namespace or ".",
            )
            # The soft-delete just made this row unavailable for real
            # — a later structure in the same run reclaiming this old
            # name must not read a stale cached hit and steal this
            # identity; invalidate it in place instead of a re-query.
            self._snapshot.forget_state_row(
                namespace=old_namespace or ".",
                structure_name=old_name,
            )
            return old_row.uid, old_row.deployment_id

        return None, None

    def write_schema_metadata(
        self,
        namespaced_structure: NamespacedStructure,
        schema_snapshot: StructureSchemaSnapshot,
        structure_schema_hash: str,
        structure_hash: str,
        diff: StructureDiff,
        statements: list[DDLStatement],
        ddl_applied: bool,
        pending_structure_renames: list[RenameStructureDirective] | None = None,
    ) -> str:
        """Write metadata after deployment using precomputed snapshot and hashes.

        Returns the deployment_id of the created record.
        """
        namespace = namespaced_structure.namespace
        structure = namespaced_structure.model

        structure_snapshot = build_structure_snapshot_json(
            structure=structure,
        )

        uid, previous_id = self.resolve_backend_identity(
            namespace=namespace,
            structure_name=structure.name,
            pending_structure_renames=pending_structure_renames or [],
        )

        record = StructureSchemaHistoryRecord.build(
            namespace=namespace,
            object_path=self._deploy_schema,
            structure_name=structure.name,
            structure_schema_snapshot=schema_snapshot,
            structure_snapshot=structure_snapshot,
            structure_schema_hash=structure_schema_hash,
            structure_hash=structure_hash,
            diff=diff,
            ddl_applied=ddl_applied,
            ddl_statements=[st.sql for st in statements],
            previous_deployment_id=previous_id,
            uid=uid,
        )

        self._metadata_manager.write_history_record(
            metadata_schema=self._metadata_schema,
            record=record,
        )
        self._metadata_manager.upsert_current_schema(
            metadata_schema=self._metadata_schema,
            record=record,
        )
        # Keep the cache authoritative for this structure in case a
        # later call in the same run reads its state row again.
        self._snapshot.set_state_row(
            namespace=namespace,
            structure_name=structure.name,
            row=StructureMetadataRow.from_history_record(record=record),
        )

        return record.deployment_id
