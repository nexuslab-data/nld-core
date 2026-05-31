import datetime

from pydantic import Field

from nld.pydantic.base_model import NldBaseModel


class FlowDeploymentFlowChangeRow(NldBaseModel):
    """One row per flow change within a deployment.

    Stored in the ``_nld_flow_deployment_flow_change`` metadata table.
    Links to the flow history record via ``flow_history_id`` when
    a history entry exists (successful deployments). For skipped or
    failed flows the ``flow_history_id`` is None.
    """

    deployment_id: str = Field(json_schema_extra={"primary_key": True})
    flow_name: str = Field(json_schema_extra={"primary_key": True})
    namespace: str = Field(json_schema_extra={"primary_key": True})
    backfill_status: str
    changed_at: datetime.datetime
    error_message: str | None = None
    flow_history_id: str | None = None


class FlowDeploymentRow(NldBaseModel):
    """One row per manifest execution.

    Stored in the ``_nld_flow_deployment`` metadata table.
    """

    deployment_id: str = Field(json_schema_extra={"primary_key": True})
    manifest_id: str
    manifest_name: str
    status: str = "running"
    started_at: datetime.datetime
    completed_at: datetime.datetime | None = None
    flows_in_error: int = 0
    flows_in_success: int = 0
    flows_skipped: int = 0
    flows_total: int = 0
    structures_in_error: int = 0
    structures_in_success: int = 0
    structures_skipped: int = 0
    structures_total: int = 0


class FlowDeploymentStructureChangeRow(NldBaseModel):
    """Links a flow deployment to a structure deployment.

    Stored in the ``_nld_flow_deployment_structure_change`` metadata table.
    """

    deployment_id: str = Field(json_schema_extra={"primary_key": True})
    structure_deployment_id: str = Field(json_schema_extra={"primary_key": True})
    changed_at: datetime.datetime


class FlowDeployHistoryRow(NldBaseModel):
    """Immutable log entry for a single flow deployment event.

    Stored in the ``_nld_flow_history`` metadata table.
    """

    deployment_id: str = Field(json_schema_extra={"primary_key": True})
    namespace: str
    flow_name: str
    deployed_at: datetime.datetime
    flow_definition_hash: str
    flow_sql_hash: str | None = None
    flow_yaml_hash: str
    flow_python_hash: str
    flow_yaml_snapshot: str | None = None
    target_structure_hash: str | None = None
    diff_action: str
    backfill_strategy: str
    manifest_deployment_id: str | None = None
    predecessor_hashes: dict[str, str] | None = None
    previous_deployment_id: str | None = None


class FlowDeployMetadataRow(NldBaseModel):
    """Current deployment state for a single flow.

    Stored in the ``_nld_flow_state`` metadata table.  The
    composite primary key is (namespace, flow_name).
    """

    namespace: str = Field(json_schema_extra={"primary_key": True})
    flow_name: str = Field(json_schema_extra={"primary_key": True})
    deployment_id: str
    deployed_at: datetime.datetime
    flow_definition_hash: str
    flow_sql_hash: str | None = None
    flow_yaml_hash: str
    flow_python_hash: str
    flow_yaml_snapshot: str | None = None
    last_deployment_id: str | None = None
    predecessor_hashes: dict[str, str] | None = None
    target_structure_hash: str | None = None
