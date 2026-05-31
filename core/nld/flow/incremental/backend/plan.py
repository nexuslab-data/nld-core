from __future__ import annotations

import datetime

from pydantic import ConfigDict, Field, field_validator

from nld.flow.incremental.models import FlowStatePlan
from nld.pydantic import NldBaseModel
from nld.utils.datetime_util import normalize_to_utc

__all__ = [
    "BackendStatePlanRow",
    "row_to_state_plan",
    "state_plan_to_row",
]


class BackendStatePlanRow(NldBaseModel):
    """Backend-agnostic state-plan row backing the planned-state lifecycle.

    Carries only the lifecycle metadata shared by every backend. The
    strategy-specific processing-state payload lives in a sibling
    per-strategy slot referenced by ``plan_state_uid`` (a processing-state
    table for PostgreSQL, a sibling file for S3).

    The ``functional_key`` / ``primary_key`` ``json_schema_extra`` drive the
    PostgreSQL state-plan table DDL; they are inert metadata for backends
    (such as S3) that serialise the row to JSON instead.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "functional_key": {
                "fields": ["plan_state_uid"],
                "name": "fk_incremental_plans",
            },
        },
    )

    plan_state_uid: str = Field(json_schema_extra={"primary_key": True})
    flow_namespace: str
    flow_name: str
    status: str
    strategy: str
    computed_at: datetime.datetime
    status_changed_at: datetime.datetime
    requestor: str | None = None
    executed_by_flow_uid: str | None = None

    @field_validator(
        "computed_at",
        "status_changed_at",
        mode="before",
    )
    @classmethod
    def normalize_timestamps(
        cls,
        value: datetime.datetime | str | None,
    ) -> datetime.datetime | None:
        """Parse ISO datetimes from JSON round-trips and normalize to UTC."""
        if isinstance(value, str):
            value = datetime.datetime.fromisoformat(value)
        return normalize_to_utc(value)


def state_plan_to_row(
    state_plan: FlowStatePlan,
) -> BackendStatePlanRow:
    """Project a ``FlowStatePlan`` onto its backend-agnostic row form."""
    return BackendStatePlanRow(
        plan_state_uid=state_plan.plan_state_uid,
        flow_namespace=state_plan.flow_namespace,
        flow_name=state_plan.flow_name,
        status=state_plan.status,
        strategy=state_plan.strategy,
        computed_at=state_plan.computed_at,
        status_changed_at=state_plan.status_changed_at,
        requestor=state_plan.requestor,
        executed_by_flow_uid=state_plan.executed_by_flow_uid,
    )


def row_to_state_plan(
    row: BackendStatePlanRow,
) -> FlowStatePlan:
    """Hydrate a ``FlowStatePlan`` from its backend-agnostic row form."""
    return FlowStatePlan(
        plan_state_uid=row.plan_state_uid,
        flow_namespace=row.flow_namespace,
        flow_name=row.flow_name,
        status=row.status,
        strategy=row.strategy,
        computed_at=row.computed_at,
        status_changed_at=row.status_changed_at,
        requestor=row.requestor,
        executed_by_flow_uid=row.executed_by_flow_uid,
    )
