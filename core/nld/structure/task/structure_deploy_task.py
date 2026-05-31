from __future__ import annotations

from typing import Any, cast

from nld.connector.base.connector import SQLDataConnector
from nld.exceptions import NldRuntimeException
from nld.parameters import ExecutionParameterDefinition
from nld.pydantic.namespace import NldNamespace
from nld.structure.deploy.structure_deploy_manager import StructureDeployManager
from nld.structure.deploy.structure_diff import DiffAction, StructureDiff
from nld.structure.deploy.structure_diff_ddl_generator import DDLStatement
from nld.structure.deploy.structure_metadata_backend_manager import (
    StructureMetadataBackendManager,
)
from nld.structure.structure.structure import NamespacedStructure, Structure
from nld.task import StandardTask
from nld.utils import resolve_variables


class StructureDeployTask(StandardTask):
    """Deploy structure definitions to a database.

    Orchestrates the deployment by resolving structures to deploy
    and delegating per-structure deployment to StructureDeployManager.

    Example:
        >>> task = StructureDeployTask(
        ...     namespace="source.raw",
        ... )
    """

    init_params = [
        ExecutionParameterDefinition(
            name="name",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="namespace",
            mandatory=False,
        ),
    ]
    run_params = [
        ExecutionParameterDefinition(
            name="plan_only",
            mandatory=False,
        ),
    ]

    def __init__(
        self,
        name: str | None = None,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self.execution_context.load_entities()

        config = self.execution_context.project.structure_config

        resolved_namespace = self._resolve_namespace(
            namespace=namespace,
            structure_name=name,
        )

        mapping = config.get_mapping(namespace=resolved_namespace)

        connector = self.execution_context.get_data_connector(
            mapping.default_connection_name,
            open_connection=True,
        )

        self.config = config
        self.connector = connector
        self.mapping = mapping
        self.namespace = resolved_namespace
        self.structures_to_deploy = self._load_structures_to_deploy(
            namespace=resolved_namespace,
            structure_name=name,
        )

    def run(
        self,
        plan_only: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Execute the structure deployment.

        Args:
            plan_only: When True, only log DDL without executing.
            **kwargs: Additional keyword arguments.

        Returns:
            True if deployment completed successfully.
        """
        schema_name = self.mapping.schema_name

        sql_connector = cast(SQLDataConnector[Any], self.connector)

        # Resolve metadata connector and schema from project config
        metadata_backend_connector_name = (
            self.execution_context.project.metadata_backend_connector
        )
        if metadata_backend_connector_name is not None:
            metadata_connector = cast(
                SQLDataConnector[Any],
                self.execution_context.get_data_connector(
                    metadata_backend_connector_name,
                    open_connection=True,
                ),
            )
            metadata_schema = schema_name
        else:
            metadata_connector = sql_connector
            metadata_schema = schema_name

        metadata_manager = StructureMetadataBackendManager(
            metadata_connector=metadata_connector,
        )
        if not plan_only:
            metadata_manager.ensure_metadata_tables(
                metadata_schema=metadata_schema,
            )

        variables = resolve_variables(
            project_variables=self.execution_context.project.variables,
        )
        deploy_manager = StructureDeployManager(
            structure_connector=sql_connector,
            deploy_schema=schema_name,
            metadata_backend_connector=metadata_connector,
            metadata_schema=metadata_schema,
            variables=variables,
        )

        for namespaced_structure in self.structures_to_deploy:
            try:
                result = deploy_manager.deploy(
                    namespaced_structure=namespaced_structure,
                    plan_only=plan_only,
                )
            except Exception as ex:
                structure_name = namespaced_structure.model.name
                msg = f"Error deploying structure '{structure_name}': {ex}"
                raise NldRuntimeException(msg) from ex

            if plan_only:
                self._log_statements(statements=result.statements)
                self._log_plan_summary(
                    structure=namespaced_structure.model,
                    diff=result.diff,
                    statements=result.statements,
                )
            elif result.deployed:
                summary = self._build_deploy_summary(
                    structure=namespaced_structure.model,
                    diff=result.diff,
                )
                self.log_info(summary)
            else:
                self.log_info(
                    f"Structure '{namespaced_structure.model.name}' is in sync"
                )

        return True

    def _log_plan_summary(
        self,
        structure: Structure,
        diff: StructureDiff,
        statements: list[DDLStatement],
    ) -> None:
        """Log a summary of changes detected during plan phase."""
        if not diff.has_changes():
            self.log_info(f"[PLAN] Structure '{structure.name}' is in sync")
            return

        field_changes = len(diff.field_diffs)
        char_changes = len(diff.characterisation_diffs)
        self.log_info(
            f"[PLAN] Structure '{structure.name}': "
            f"{field_changes} field change(s), "
            f"{char_changes} characterisation change(s), "
            f"{len(statements)} DDL statement(s) would be executed"
        )

    def _resolve_namespace(
        self,
        namespace: str | None,
        structure_name: str | None,
    ) -> str:
        """Resolve the effective namespace.

        When a structure_name is provided, retrieves the NamespacedStructure
        from the entity registry and uses its namespace.
        """
        if structure_name is not None:
            entity_registry = self.execution_context.entity_registry
            namespaced_structure = entity_registry.get_structure(
                entity_key=structure_name,
                namespace=namespace,
            )
            return namespaced_structure.namespace
        if namespace is None:
            return NldNamespace.ROOT_VALUE
        return namespace

    def _load_structures_to_deploy(
        self,
        namespace: str,
        structure_name: str | None,
    ) -> list[NamespacedStructure]:
        """Load structures to deploy from the entity registry."""
        entity_registry = self.execution_context.entity_registry
        if structure_name is not None:
            namespaced = entity_registry.get_structure(
                entity_key=structure_name,
                namespace=namespace,
            )
            if namespaced.model.is_external_source():
                return []
            if not namespaced.model.is_table():
                msg = (
                    f"Structure '{structure_name}' is of type "
                    f"'{namespaced.model.structure_type}' and cannot be deployed. "
                    f"Only TABLE structures are supported"
                )
                raise NldRuntimeException(msg)
            return [namespaced]

        structure_dict = entity_registry.get_structure_dict(
            namespace=namespace,
        )
        structures: list[NamespacedStructure] = []
        for ns in structure_dict.values():
            if ns.model.is_table() and not ns.model.is_external_source():
                structures.append(ns)
        return structures

    def _build_deploy_summary(
        self,
        structure: Structure,
        diff: StructureDiff,
    ) -> str:
        """Build a human-readable summary of deployed changes."""
        if not diff.has_changes() and not diff.is_new_table():
            return (
                f"Structure '{structure.name}' deployed: "
                f"definition updated (no schema changes)"
            )

        field_counts: dict[DiffAction, int] = {}
        for field_diff in diff.field_diffs:
            field_counts[field_diff.action] = field_counts.get(field_diff.action, 0) + 1

        char_counts: dict[DiffAction, int] = {}
        for char_diff in diff.characterisation_diffs:
            char_counts[char_diff.action] = char_counts.get(char_diff.action, 0) + 1

        parts = []
        if DiffAction.ADD in field_counts:
            parts.append(f"{field_counts[DiffAction.ADD]} field(s) added")
        if DiffAction.MODIFY in field_counts:
            parts.append(f"{field_counts[DiffAction.MODIFY]} field(s) modified")
        if DiffAction.DROP in field_counts:
            parts.append(f"{field_counts[DiffAction.DROP]} field(s) dropped")
        if DiffAction.ADD in char_counts:
            parts.append(
                f"{char_counts[DiffAction.ADD]} characterisation(s) added",
            )
        if DiffAction.MODIFY in char_counts:
            parts.append(
                f"{char_counts[DiffAction.MODIFY]} characterisation(s) modified",
            )
        if DiffAction.DROP in char_counts:
            parts.append(
                f"{char_counts[DiffAction.DROP]} characterisation(s) dropped",
            )

        action = "created" if diff.is_new_table() else "deployed"
        if not parts:
            return f"Structure '{structure.name}' {action}"
        detail = ", ".join(parts)
        return f"Structure '{structure.name}' {action}: {detail}"

    def _log_statements(self, statements: list[DDLStatement]) -> None:
        """Log all generated DDL statements."""
        if not statements:
            self.log_info("No DDL statements to execute")
            return
        for statement in statements:
            self.log_info(f"[DDL] {statement.description}: {statement.sql}")
