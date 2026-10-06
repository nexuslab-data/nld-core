import datetime
import json
from typing import Any, cast

from pydantic import Field

from nld.connector.base.connector import SQLDataConnector
from nld.logging.logger import NldLoggable
from nld.pydantic.base_model import NldBaseModel

NLD_DEPLOYMENT_SCOPE_TABLE = "_nld_deployment_scope"


class DeploymentScopeRow(NldBaseModel):
    """The scope one deploy run was applied to.

    Stored in the ``_nld_deployment_scope`` metadata table and joined to
    the run tables (``_nld_flow_deployment``, ``_nld_structure_deployment``)
    on ``deployment_id``. Kept in a table of its own because the existing
    run tables cannot gain columns on a live backend. ``unit_namespaces``,
    ``deploy_groups`` and ``lock_keys`` are JSON lists; a full-project
    deploy records no requested namespace and empty lists. Column names
    avoid the words an engine reserves (``GROUPS`` on BigQuery).
    """

    deployment_id: str = Field(json_schema_extra={"primary_key": True})
    command: str
    recorded_at: datetime.datetime
    requested_namespace: str | None = None
    requested_name: str | None = None
    unit_namespaces: str = "[]"
    deploy_groups: str = "[]"
    lock_keys: str = "[]"

    @classmethod
    def build(
        cls,
        deployment_id: str,
        command: str,
        recorded_at: datetime.datetime,
        requested_namespace: str | None,
        requested_name: str | None,
        unit_namespaces: list[str],
        deploy_groups: list[str],
        lock_keys: list[str],
    ) -> "DeploymentScopeRow":
        """Build a row, serialising the list attributes as JSON."""
        return cls(
            deployment_id=deployment_id,
            command=command,
            recorded_at=recorded_at,
            requested_namespace=requested_namespace,
            requested_name=requested_name,
            unit_namespaces=json.dumps(unit_namespaces),
            deploy_groups=json.dumps(deploy_groups),
            lock_keys=json.dumps(lock_keys),
        )


class DeploymentScopeManager(NldLoggable):
    """Records the scope of every applied deploy run."""

    def __init__(
        self,
        connector: SQLDataConnector[Any],
    ) -> None:
        super().__init__()
        self._model_manager = connector.get_model_manager()

    def ensure_table(
        self,
        metadata_schema: str,
    ) -> None:
        """Create the scope table if it does not exist."""
        self._model_manager.create_table(
            model_class=DeploymentScopeRow,
            schema_name=metadata_schema,
            table_name=NLD_DEPLOYMENT_SCOPE_TABLE,
        )

    def record(
        self,
        metadata_schema: str,
        row: DeploymentScopeRow,
    ) -> None:
        """Record the scope of one deploy run."""
        self.ensure_table(metadata_schema=metadata_schema)
        self._model_manager.insert_model(
            model=row,
            schema_name=metadata_schema,
            table_name=NLD_DEPLOYMENT_SCOPE_TABLE,
        )

    def get_scopes(
        self,
        metadata_schema: str,
    ) -> list[DeploymentScopeRow]:
        """Return the recorded scope of every applied deploy run."""
        models = self._model_manager.read_models(
            model_class=DeploymentScopeRow,
            schema_name=metadata_schema,
            table_name=NLD_DEPLOYMENT_SCOPE_TABLE,
        )
        return [cast(DeploymentScopeRow, model) for model in models]
