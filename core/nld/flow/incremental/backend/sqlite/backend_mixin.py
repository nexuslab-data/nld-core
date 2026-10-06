from __future__ import annotations

import abc
from typing import TYPE_CHECKING, cast

from nld.flow.backend.sqlite.backend_mixin import SQLiteBackendMixin
from nld.flow.backend.sqlite.utils import (
    SQLITE_BACKEND_INCREMENTAL_TABLE_PREFIX,
)
from nld.flow.incremental.backend.plan import (
    BackendStatePlanRow,
    row_to_state_plan,
    state_plan_to_row,
)
from nld.flow.incremental.models import FlowStatePlan

if TYPE_CHECKING:
    from nld.connector.sqlite.engine.sqlite_native.adapter.pydantic.model_manager import (  # noqa: E501
        NldBaseModelSQLiteManager,
    )

SQLITE_INCREMENTAL_PLANS_TABLE_NAME = f"{SQLITE_BACKEND_INCREMENTAL_TABLE_PREFIX}_plans"


class SQLiteIncrementalBackendMixin(SQLiteBackendMixin):
    """Connector-specific planned-state persistence for SQLite.

    Owns only the I/O for the state-plan table
    (``_nld_incremental_plans``): write, read and list state plans.
    The generic plan lifecycle (cancel-on-supersede, COMPLETED /
    CANCELLED transitions, latest-PLANNED selection) lives in
    ``IncrementalStateManager``. The strategy-specific
    processing-state table is delegated to the implementing backend
    through the ``_ensure_planned_processing_state_table_exists`` /
    ``write_planned_processing_state`` / ``read_planned_processing_state``
    hooks.

    Extends ``SQLiteBackendMixin`` so the implementing class
    automatically inherits ``backend_connector`` / ``parameters`` /
    ``backend_schema_name`` and only needs to bring in the incremental
    plumbing.

    Requires from the implementing class:
      - ``pydantic_manager: NldBaseModelSQLiteManager``
      - ``flow_namespace: str``, ``flow_name: str``
    """

    pydantic_manager: NldBaseModelSQLiteManager
    flow_namespace: str
    flow_name: str

    # SQLite persists the state-plan table and processing-state payloads
    # in the target file, so every backend built on this mixin can hold
    # a plan.
    supports_planned_state = True

    @abc.abstractmethod
    def _ensure_planned_processing_state_table_exists(self) -> None:
        """Create the per-strategy ``..._planned_state`` processing-state table."""

    def _ensure_planned_state_table_exists(self) -> None:
        """Create the state-plan table + the strategy-specific processing-state."""
        self.pydantic_manager.create_table(
            model_class=BackendStatePlanRow,
            schema_name=self.backend_schema_name,
            table_name=SQLITE_INCREMENTAL_PLANS_TABLE_NAME,
            table_exists="skip",
            track_timestamps=True,
            use_functional_key_as_primary=True,
        )
        self._ensure_planned_processing_state_table_exists()

    # ---- State-plan persistence primitives. ----

    def read_state_plan(
        self,
        plan_state_uid: str,
    ) -> FlowStatePlan | None:
        """Return the state plan for ``plan_state_uid`` scoped to this flow."""
        rows = cast(
            list[BackendStatePlanRow],
            self.pydantic_manager.read_models(
                model_class=BackendStatePlanRow,
                schema_name=self.backend_schema_name,
                table_name=SQLITE_INCREMENTAL_PLANS_TABLE_NAME,
                where_conditions={
                    "plan_state_uid": plan_state_uid,
                    "flow_namespace": self.flow_namespace,
                    "flow_name": self.flow_name,
                },
                limit=1,
            ),
        )
        if not rows:
            return None
        return row_to_state_plan(row=rows[0])

    def read_state_plans(
        self,
    ) -> list[FlowStatePlan]:
        """Return every state plan for this flow, newest first."""
        rows = cast(
            list[BackendStatePlanRow],
            self.pydantic_manager.read_models(
                model_class=BackendStatePlanRow,
                schema_name=self.backend_schema_name,
                table_name=SQLITE_INCREMENTAL_PLANS_TABLE_NAME,
                where_conditions={
                    "flow_namespace": self.flow_namespace,
                    "flow_name": self.flow_name,
                },
                order_by=["-computed_at"],
            ),
        )
        return [row_to_state_plan(row=row) for row in rows]

    def write_state_plan(
        self,
        state_plan: FlowStatePlan,
    ) -> None:
        """Insert or update the state-plan row backing a single state plan."""
        self.pydantic_manager.upsert_model(
            model=state_plan_to_row(state_plan=state_plan),
            schema_name=self.backend_schema_name,
            table_name=SQLITE_INCREMENTAL_PLANS_TABLE_NAME,
            conflict_fields=["plan_state_uid"],
            commit=True,
            track_timestamps=True,
        )
