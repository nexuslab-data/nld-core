from datetime import datetime
from typing import Any

from pydantic import Field as PydanticField

from nld.pydantic import NldBaseModel

STATE_STATUS_OK: str = "ok"
STATE_STATUS_UNAVAILABLE: str = "unavailable"

SLA_STATUS_ON_TIME: str = "on_time"
SLA_STATUS_LATE: str = "late"
SLA_STATUS_FAILED: str = "failed"
SLA_STATUS_RUNNING: str = "running"
SLA_STATUS_NEVER_RUN: str = "never_run"
SLA_STATUS_UNKNOWN: str = "unknown"


class DocsStateSection(NldBaseModel):
    """Availability of one live-state section.

    Part A of the UI never depends on a database, so every state section
    carries its own availability and the reason it could not be read. The
    reason is a short category, never the driver's message: those routinely
    embed host names and user names, and the page may be served to others.
    """

    status: str = STATE_STATUS_UNAVAILABLE
    message: str | None = None


class DocsBackendState(NldBaseModel):
    """Where the metadata backend is and whether it answered."""

    section: DocsStateSection = PydanticField(default_factory=DocsStateSection)
    connection_name: str | None = None
    connector_type: str | None = None
    metadata_schema: str | None = None


class DocsStructureDeploymentState(NldBaseModel):
    """What the deployment backend holds for one structure."""

    structure_id: str
    namespace: str
    structure_name: str
    deployed_at: datetime | None = None
    deployment_id: str | None = None
    deployed_hash: str | None = None
    repository_hash: str | None = None
    drift: bool = False
    deployed: bool = False


class DocsFlowDeploymentState(NldBaseModel):
    """What the deployment backend holds for one flow."""

    flow_id: str
    namespace: str
    flow_name: str
    deployed_at: datetime | None = None
    deployment_id: str | None = None
    deployed_yaml_hash: str | None = None
    repository_yaml_hash: str | None = None
    drift: bool = False
    deployed: bool = False


class DocsFlowExecutionState(NldBaseModel):
    """The latest recorded execution of one flow.

    ``reached`` tells whether the flow's state backend answered at all: a
    flow whose backend could not be read has no record but is not "never
    run", and the SLA classification keeps the two apart.
    """

    flow_id: str
    reached: bool = False
    flow_uid: str | None = None
    execution_status: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    execution_error: str | None = None
    source_last_updated_at: datetime | None = None
    previous_layer_last_updated_at: datetime | None = None
    steps: list[dict[str, Any]] = PydanticField(default_factory=list)
    message: str | None = None


class DocsFlowSlaState(NldBaseModel):
    """The declared cadence of a flow compared with what actually ran.

    ``tolerance_ratio`` is the multiplier applied to the expected interval
    before a flow is called late, carried so the page can say which rule
    produced the badge.
    """

    flow_id: str
    environment: str | None = None
    frequency: str | None = None
    expected_interval_seconds: int | None = None
    tolerance_ratio: float | None = None
    last_success_at: datetime | None = None
    last_status: str | None = None
    age_seconds: float | None = None
    status: str = SLA_STATUS_UNKNOWN


class DocsStructureFreshnessState(NldBaseModel):
    """How old the data of one structure is, and where that age comes from."""

    structure_id: str
    last_updated_at: datetime | None = None
    age_seconds: float | None = None
    source: str | None = None
    produced_by: str | None = None


class DocsLiveState(NldBaseModel):
    """Everything the UI knows about the running system, at one instant."""

    collected_at: datetime
    environment: str | None = None
    available: bool = False
    message: str | None = None
    backend: DocsBackendState = PydanticField(default_factory=DocsBackendState)
    structure_deployments: list[DocsStructureDeploymentState] = PydanticField(
        default_factory=list
    )
    flow_deployments: list[DocsFlowDeploymentState] = PydanticField(
        default_factory=list
    )
    executions: list[DocsFlowExecutionState] = PydanticField(default_factory=list)
    sla: list[DocsFlowSlaState] = PydanticField(default_factory=list)
    freshness: list[DocsStructureFreshnessState] = PydanticField(default_factory=list)
    deployment_section: DocsStateSection = PydanticField(
        default_factory=DocsStateSection
    )
    execution_section: DocsStateSection = PydanticField(
        default_factory=DocsStateSection
    )
