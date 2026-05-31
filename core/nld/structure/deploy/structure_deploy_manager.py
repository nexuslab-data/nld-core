from __future__ import annotations

import dataclasses
from typing import Any

from nld.connector.base.connector import SQLDataConnector
from nld.exceptions import NldRuntimeException
from nld.pydantic.base_model import NldBaseModel
from nld.structure.deploy.structure_diff import StructureDiff
from nld.structure.deploy.structure_diff_computer import StructureDiffComputer
from nld.structure.deploy.structure_diff_ddl_generator import DDLStatement
from nld.structure.deploy.structure_metadata_backend_manager import (
    StructureMetadataBackendManager,
)
from nld.structure.deploy.structure_schema_history import (
    StructureSchemaHistoryRecord,
    StructureSchemaSnapshot,
    build_structure_snapshot_json,
    compute_structure_hash,
    compute_structure_schema_hash,
)
from nld.structure.structure.structure import NamespacedStructure, Structure
from nld.utils.jinja_utils import render_template


class StructureChangeSet(NldBaseModel):
    """Computed structure changes: diff and DDL statements."""

    diff: StructureDiff
    statements: list[DDLStatement]


@dataclasses.dataclass(frozen=True)
class StructureDeployResult:
    """Result of a single structure deployment."""

    deployed: bool
    deployment_id: str | None
    diff: StructureDiff
    statements: list[DDLStatement]


class StructureDeployManager:
    """Deploys a single structure to the database.

    Handles diff computation, DDL generation and execution,
    and schema metadata recording for one structure at a time.
    """

    def __init__(
        self,
        structure_connector: SQLDataConnector[Any],
        deploy_schema: str,
        metadata_backend_connector: SQLDataConnector[Any] | None = None,
        metadata_schema: str | None = None,
        variables: dict[str, str] | None = None,
    ) -> None:
        self._connector = structure_connector
        self._ddl_generator = structure_connector.get_structure_diff_ddl_generator()
        self._diff_computer = StructureDiffComputer()
        self._deploy_schema = deploy_schema
        self._variables = variables or {}
        self._metadata_manager = (
            StructureMetadataBackendManager(
                metadata_connector=metadata_backend_connector,
            )
            if metadata_backend_connector is not None
            else None
        )
        self._metadata_schema = metadata_schema
        self._reader = structure_connector.get_structure_reader()

    def compute_change_set(
        self,
        structure: Structure,
    ) -> StructureChangeSet:
        """Compute diff and DDL statements without executing or recording metadata."""
        diff = self.compute_structure_diff(structure=structure)
        statements = self._generate_statements(
            diff=diff,
            structure=structure,
        )
        return StructureChangeSet(
            diff=diff,
            statements=statements,
        )

    def deploy(
        self,
        namespaced_structure: NamespacedStructure,
        plan_only: bool = False,
    ) -> StructureDeployResult:
        """Deploy a single structure to the database.

        Computes lightweight hashes early to skip expensive operations
        when nothing has changed since the last deployment.

        Args:
            namespaced_structure: The structure definition with its
                namespace to deploy.
            plan_only: When True, compute diff and generate DDL
                without executing or recording metadata.

        Returns:
            A StructureDeployResult with the deployment outcome,
            diff, and generated DDL statements.
        """
        if self._metadata_manager is None or self._metadata_schema is None:
            raise NldRuntimeException(
                "metadata_manager and metadata_schema are required for deploy()"
            )

        namespace = namespaced_structure.namespace
        structure = namespaced_structure.model

        schema_snapshot = StructureSchemaSnapshot.from_structure(
            structure=structure,
            namespace=namespace,
        )
        new_schema_hash = compute_structure_schema_hash(
            schema_snapshot=schema_snapshot,
        )
        new_structure_hash = compute_structure_hash(structure=structure)

        if not plan_only:
            prev_schema_hash, prev_structure_hash = (
                self._metadata_manager.get_previous_hashes(
                    metadata_schema=self._metadata_schema,
                    structure_name=structure.name,
                    namespace=namespace,
                )
            )

            schema_hash_unchanged = (
                prev_schema_hash is not None and prev_schema_hash == new_schema_hash
            )
            structure_hash_unchanged = (
                prev_structure_hash is not None
                and prev_structure_hash == new_structure_hash
            )

            if schema_hash_unchanged and structure_hash_unchanged:
                empty_diff = StructureDiff(
                    structure_name=structure.name,
                    table_exists=True,
                )
                return StructureDeployResult(
                    deployed=False,
                    deployment_id=None,
                    diff=empty_diff,
                    statements=[],
                )

        change_set = self.compute_change_set(
            structure=structure,
        )
        diff = change_set.diff
        statements = change_set.statements

        if plan_only:
            return StructureDeployResult(
                deployed=False,
                deployment_id=None,
                diff=diff,
                statements=statements,
            )

        has_schema_changes = diff.has_changes()
        has_definition_changes = not structure_hash_unchanged

        if not has_schema_changes and not has_definition_changes:
            return StructureDeployResult(
                deployed=False,
                deployment_id=None,
                diff=diff,
                statements=statements,
            )

        ddl_applied = False
        if has_schema_changes and statements:
            self._execute_statements(statements=statements)
            ddl_applied = True

        self.execute_sql_hooks(structure=structure)

        structure_deployment_id = self._write_schema_metadata_on_backend(
            namespaced_structure=namespaced_structure,
            schema_snapshot=schema_snapshot,
            structure_schema_hash=new_schema_hash,
            structure_hash=new_structure_hash,
            diff=diff,
            statements=statements if has_schema_changes else [],
            ddl_applied=ddl_applied,
        )

        return StructureDeployResult(
            deployed=True,
            deployment_id=structure_deployment_id,
            diff=diff,
            statements=statements,
        )

    def compute_structure_diff(self, structure: Structure) -> StructureDiff:
        """Compute the diff between desired and actual schema."""
        return self._diff_computer.compute_from_database(
            structure=structure,
            reader=self._reader,
            schema_name=self._deploy_schema,
        )

    def _generate_statements(
        self,
        diff: StructureDiff,
        structure: Structure,
    ) -> list[DDLStatement]:
        """Generate DDL statements from a diff."""
        return self._ddl_generator.generate(
            diff=diff,
            structure=structure,
            schema_name=self._deploy_schema,
        )

    def _build_hook_template_variables(
        self,
        structure: Structure,
    ) -> dict[str, str]:
        """Build the Jinja template variables available in structure-level hooks.

        Custom hook variables (from project config and env vars) are
        included but cannot shadow built-in variables.
        """
        return {
            **self._variables,
            "schema": self._deploy_schema,
            "structure_name": structure.name,
            "object_path": f"{self._deploy_schema}.{structure.name}",
        }

    def execute_sql_hooks(
        self,
        structure: Structure,
    ) -> None:
        """Execute pre- and post-deployment SQL hooks on the structure.

        Renders each hook statement through Jinja with structure
        template variables, executes it, and commits the transaction.
        """
        hooks = (
            structure.get_all_pre_deployment_sql_hooks()
            + structure.get_all_post_deployment_sql_hooks()
        )
        if not hooks:
            return
        template_variables = self._build_hook_template_variables(
            structure=structure,
        )
        for hook in hooks:
            sql = render_template(
                hook,
                **template_variables,
            )
            self._connector.execute_query(sql)
        connection = self._connector.connection_wrapper.connection
        if connection is not None and hasattr(connection, "commit"):
            connection.commit()

    def _execute_statements(
        self,
        statements: list[DDLStatement],
    ) -> None:
        """Execute DDL statements against the database."""
        for statement in statements:
            self._connector.execute_query(statement.sql)

    def _write_schema_metadata_on_backend(
        self,
        namespaced_structure: NamespacedStructure,
        schema_snapshot: StructureSchemaSnapshot,
        structure_schema_hash: str,
        structure_hash: str,
        diff: StructureDiff,
        statements: list[DDLStatement],
        ddl_applied: bool,
    ) -> str:
        """Write metadata after deployment using precomputed snapshot and hashes.

        Returns the deployment_id of the created record.
        """
        assert self._metadata_manager is not None
        assert self._metadata_schema is not None

        namespace = namespaced_structure.namespace
        structure = namespaced_structure.model

        structure_snapshot = build_structure_snapshot_json(
            structure=structure,
        )

        previous_id = self._metadata_manager.get_previous_deployment_id(
            metadata_schema=self._metadata_schema,
            structure_name=structure.name,
            namespace=namespace,
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
        )

        self._metadata_manager.write_history_record(
            metadata_schema=self._metadata_schema,
            record=record,
        )
        self._metadata_manager.upsert_current_schema(
            metadata_schema=self._metadata_schema,
            record=record,
        )

        return record.deployment_id
