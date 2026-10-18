import abc
import datetime
import json
from collections.abc import Sequence
from typing import Any, ClassVar, cast

from pydantic import ConfigDict, Field, field_validator

from nld.connector.base.connector import DataConnector
from nld.flow.incremental.impl.by_target_period.backend.base_with_pydantic import (
    ByTargetPeriodStateBackendManager,
)
from nld.flow.incremental.impl.by_target_period.state import (
    ByTargetPeriodPlannedProcessingDetailedState,
    ByTargetPeriodProcessingState,
    ByTargetPeriodSinglePeriodPlannedProcessingDetailedState,
    ByTargetPeriodSinglePeriodProcessingState,
    ByTargetPeriodSinglePeriodState,
    ByTargetPeriodState,
)
from nld.flow.incremental.models import (
    IncrementalProcessingStatus,
    IncrementalStateStatus,
)
from nld.flow.incremental.models.events import (
    IncrementalBackendEngineInitialized,
)
from nld.pydantic import NldBaseModel
from nld.utils.datetime_util import get_current_datetime, normalize_to_utc

STATE_TABLE_SUFFIX = "_by_target_period_state"
PERIOD_STATE_TABLE_SUFFIX = "_by_target_period_period_state"
PROCESSING_STATE_TABLE_SUFFIX = "_by_target_period_processing_state"
PLANNED_PROCESSING_STATE_TABLE_SUFFIX = (
    "_plans_by_target_period_planned_processing_state"
)

PLANNED_PERIOD_CLASS = ByTargetPeriodSinglePeriodPlannedProcessingDetailedState


def parse_json_mapping(value: Any) -> Any:
    """Parse a JSON column returned as text by engines without a JSON type.

    PostgreSQL hands back a dict, DuckDB and SQLite may hand back the raw
    JSON text; both become the same mapping.
    """
    if isinstance(value, str):
        return json.loads(value)
    return value


class ByTargetPeriodStateRow(NldBaseModel):
    """Header row of the by_target_period state: the calendar and watermark."""

    model_config = ConfigDict(
        json_schema_extra={
            "business_key": {
                "fields": ["flow_namespace", "flow_name"],
                "name": "fk_by_target_period_state",
            }
        }
    )

    flow_name: str
    flow_namespace: str
    granularity: str | None = None
    last_scan_at: datetime.datetime | None = None
    period_timezone: str | None = None
    week_start: str | None = None

    @field_validator(
        "last_scan_at",
        mode="before",
    )
    @classmethod
    def normalize_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Normalize naive or non-UTC datetimes from DB to UTC-aware."""
        return normalize_to_utc(value)


class ByTargetPeriodPeriodStateRow(NldBaseModel):
    """One row per period of the by_target_period state."""

    model_config = ConfigDict(
        json_schema_extra={
            "business_key": {
                "fields": ["flow_namespace", "flow_name", "period_name"],
                "name": "fk_by_target_period_period_state",
            }
        }
    )

    first_processed_at: datetime.datetime | None = None
    flow_name: str
    flow_namespace: str
    last_process_error_message: str | None = None
    last_process_status: str | None = None
    last_processed_at: datetime.datetime | None = None
    last_source_modified_at: datetime.datetime | None = None
    last_successfully_processed_at: datetime.datetime | None = None
    period_name: str
    status: str | None = None

    @field_validator(
        "last_successfully_processed_at",
        "last_processed_at",
        "first_processed_at",
        "last_source_modified_at",
        mode="before",
    )
    @classmethod
    def normalize_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Normalize naive or non-UTC datetimes from DB to UTC-aware."""
        return normalize_to_utc(value)


class ByTargetPeriodProcessingStateRow(NldBaseModel):
    """One row per run; the per-period outcomes are kept as JSON."""

    model_config = ConfigDict(
        json_schema_extra={
            "business_key": {
                "fields": ["flow_namespace", "flow_name"],
                "name": "fk_by_target_period_processing_state",
            }
        }
    )

    flow_name: str
    flow_namespace: str
    flow_uid: str = Field(json_schema_extra={"primary_key": True})
    granularity: str
    period_timezone: str
    periods: dict[str, Any] | None = None
    process_error_message: str | None = None
    processing_completed_at: datetime.datetime | None = None
    processing_status: str | None = None
    scanned_at: datetime.datetime | None = None
    strategy: str
    week_start: str | None = None
    # Last write of the row, so the latest run is found on every engine
    # without relying on the connector's technical timestamp columns.
    written_at: datetime.datetime | None = None

    @field_validator(
        "scanned_at",
        "processing_completed_at",
        "written_at",
        mode="before",
    )
    @classmethod
    def normalize_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Normalize naive or non-UTC datetimes from DB to UTC-aware."""
        return normalize_to_utc(value)

    @field_validator(
        "periods",
        mode="before",
    )
    @classmethod
    def parse_periods(cls, value: Any) -> Any:
        """Accept the periods as JSON text from engines without a JSON type."""
        return parse_json_mapping(value)


class ByTargetPeriodPlannedProcessingStateRow(NldBaseModel):
    """Detail row for the by_target_period planned-state slot.

    One row per plan, the periods kept as JSON, so a plan selecting no
    period at all is still recoverable.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "business_key": {
                "fields": ["plan_state_uid"],
                "name": "fk_by_target_period_planned_processing_state",
            },
        },
    )

    flow_name: str
    flow_namespace: str
    granularity: str
    period_timezone: str
    periods: dict[str, Any] | None = None
    plan_state_uid: str = Field(json_schema_extra={"primary_key": True})
    scanned_at: datetime.datetime | None = None
    strategy: str
    week_start: str | None = None

    @field_validator(
        "scanned_at",
        mode="before",
    )
    @classmethod
    def normalize_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Normalize naive or non-UTC datetimes from DB to UTC-aware."""
        return normalize_to_utc(value)

    @field_validator(
        "periods",
        mode="before",
    )
    @classmethod
    def parse_periods(cls, value: Any) -> Any:
        """Accept the periods as JSON text from engines without a JSON type."""
        return parse_json_mapping(value)


class SQLModelByTargetPeriodStateBackendManager[DATA_CONNECTOR: DataConnector[Any]](
    ByTargetPeriodStateBackendManager[DATA_CONNECTOR],
    abc.ABC,
):
    """Shared by_target_period persistence on a SQL connector's model manager.

    Every SQL connector exposes the same Pydantic model-manager contract
    (create, read and upsert models), so the state layout and the row
    mapping live here once. A connector backend combines this class with
    its connector backend mixin (which provides ``backend_schema_name`` and,
    when available, the planned-state plan table) and sets the table names.

    The state is a header row per flow plus one row per period; a run and a
    plan are one row each with the periods kept as JSON.
    """

    param_definitions = []

    # Each connector mixin narrows the manager type; the shared code only
    # relies on the model-manager contract common to every connector.
    pydantic_manager: Any

    state_table_name: ClassVar[str]
    period_state_table_name: ClassVar[str]
    processing_state_table_name: ClassVar[str]
    planned_processing_state_table_name: ClassVar[str]

    def __init__(
        self,
        backend_connector: DATA_CONNECTOR,
        flow_namespace: str,
        flow_name: str,
        parameters: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            backend_connector=backend_connector,
            flow_namespace=flow_namespace,
            flow_name=flow_name,
            parameters=parameters,
            **kwargs,
        )

        self.pydantic_manager = self.backend_connector.get_model_manager()

        self._ensure_tables_exist()
        if self.supports_planned_state:
            self._ensure_planned_state_table_exists()

        self.log_event(
            IncrementalBackendEngineInitialized(
                backend_type=backend_connector.connection_wrapper.type,
                engine="pydantic",
                manager_class=type(self).__name__,
            ),
        )

    @property
    @abc.abstractmethod
    def backend_schema_name(self) -> str:
        """Schema holding the state tables, provided by the connector mixin."""
        raise NotImplementedError(
            "The property 'backend_schema_name' should be implemented in sub class."
        )

    def _ensure_planned_state_table_exists(self) -> None:
        """Create the planned-state tables; provided by planned-state mixins."""
        raise NotImplementedError(
            f"'_ensure_planned_state_table_exists' is not implemented "
            f"for {type(self).__name__}"
        )

    def _ensure_tables_exist(self) -> None:
        """Create the state, period state and processing state tables."""
        for model_class, table_name, use_business_key_as_primary in (
            (ByTargetPeriodStateRow, self.state_table_name, True),
            (ByTargetPeriodPeriodStateRow, self.period_state_table_name, True),
            (
                ByTargetPeriodProcessingStateRow,
                self.processing_state_table_name,
                False,
            ),
        ):
            self.pydantic_manager.create_table(
                model_class=model_class,
                schema_name=self.backend_schema_name,
                table_name=table_name,
                table_exists="skip",
                track_timestamps=True,
                use_business_key_as_primary=use_business_key_as_primary,
            )

    def _flow_conditions(self) -> dict[str, Any]:
        return {
            "flow_namespace": self.flow_namespace,
            "flow_name": self.flow_name,
        }

    def _upsert_rows(
        self,
        rows: Sequence[NldBaseModel],
        table_name: str,
        conflict_fields: list[str],
        commit: bool,
    ) -> None:
        """Upsert rows in one statement when the manager supports it."""
        if not rows:
            return
        bulk_upsert_models = getattr(self.pydantic_manager, "bulk_upsert_models", None)
        if bulk_upsert_models is not None:
            bulk_upsert_models(
                models=rows,
                schema_name=self.backend_schema_name,
                table_name=table_name,
                conflict_fields=conflict_fields,
                commit=commit,
                track_timestamps=True,
            )
            return
        for row in rows:
            self.pydantic_manager.upsert_model(
                model=row,
                schema_name=self.backend_schema_name,
                table_name=table_name,
                conflict_fields=conflict_fields,
                commit=commit,
                track_timestamps=True,
            )

    # ---- Authoritative state. ----

    def read_current_state(self) -> ByTargetPeriodState:
        """Retrieve the current by_target_period state."""
        state = self.read_post_processing_state()
        return state if state is not None else ByTargetPeriodState()

    def read_post_processing_state(self) -> ByTargetPeriodState | None:
        """Read the persisted state, None when it was never written."""
        header = cast(
            ByTargetPeriodStateRow | None,
            self.pydantic_manager.read_model(
                model_class=ByTargetPeriodStateRow,
                schema_name=self.backend_schema_name,
                table_name=self.state_table_name,
                where_conditions=self._flow_conditions(),
            ),
        )
        if header is None:
            return None
        rows = cast(
            list[ByTargetPeriodPeriodStateRow],
            self.pydantic_manager.read_models(
                model_class=ByTargetPeriodPeriodStateRow,
                schema_name=self.backend_schema_name,
                table_name=self.period_state_table_name,
                where_conditions=self._flow_conditions(),
            ),
        )
        return ByTargetPeriodState(
            granularity=header.granularity,
            period_timezone=header.period_timezone,
            week_start=header.week_start,
            last_scan_at=header.last_scan_at,
            periods={
                row.period_name: ByTargetPeriodSinglePeriodState(
                    name=row.period_name,
                    status=row.status or IncrementalStateStatus.NOT_PROCESSED,
                    last_successfully_processed_at=row.last_successfully_processed_at,
                    last_processed_at=row.last_processed_at,
                    last_process_status=(
                        row.last_process_status or IncrementalStateStatus.NOT_PROCESSED
                    ),
                    last_process_error_message=row.last_process_error_message,
                    first_processed_at=row.first_processed_at,
                    last_source_modified_at=row.last_source_modified_at,
                )
                for row in rows
            },
        )

    def write_post_processing_state(
        self,
        post_processing_flow_state: ByTargetPeriodState,
    ) -> None:
        """Upsert the state header and the rows of the periods the run changed.

        A run only touches its own periods, so the other rows of the
        history are left as they are rather than rewritten on every run.
        """
        self._upsert_rows(
            rows=[
                ByTargetPeriodStateRow(
                    flow_namespace=self.flow_namespace,
                    flow_name=self.flow_name,
                    granularity=post_processing_flow_state.granularity,
                    period_timezone=post_processing_flow_state.period_timezone,
                    week_start=post_processing_flow_state.week_start,
                    last_scan_at=post_processing_flow_state.last_scan_at,
                ),
            ],
            table_name=self.state_table_name,
            conflict_fields=["flow_namespace", "flow_name"],
            commit=False,
        )
        self._upsert_rows(
            rows=[
                ByTargetPeriodPeriodStateRow(
                    flow_namespace=self.flow_namespace,
                    flow_name=self.flow_name,
                    period_name=period.name,
                    status=period.status,
                    last_successfully_processed_at=period.last_successfully_processed_at,
                    last_processed_at=period.last_processed_at,
                    last_process_status=period.last_process_status,
                    last_process_error_message=period.last_process_error_message,
                    first_processed_at=period.first_processed_at,
                    last_source_modified_at=period.last_source_modified_at,
                )
                for period in post_processing_flow_state.get_changed_periods()
            ],
            table_name=self.period_state_table_name,
            conflict_fields=["flow_namespace", "flow_name", "period_name"],
            commit=False,
        )

    # ---- Processing state. ----

    def read_processing_state(self) -> ByTargetPeriodProcessingState | None:
        """Read the processing state of the most recent run of this flow."""
        row = cast(
            ByTargetPeriodProcessingStateRow | None,
            self.pydantic_manager.read_model(
                model_class=ByTargetPeriodProcessingStateRow,
                schema_name=self.backend_schema_name,
                table_name=self.processing_state_table_name,
                where_conditions=self._flow_conditions(),
                order_by=["-written_at"],
            ),
        )
        if row is None:
            return None
        return ByTargetPeriodProcessingState(
            flow_uid=row.flow_uid,
            strategy=row.strategy,
            granularity=row.granularity,
            period_timezone=row.period_timezone,
            week_start=row.week_start,
            scanned_at=row.scanned_at,
            processing_status=(
                row.processing_status or IncrementalProcessingStatus.TO_BE_PROCESSED
            ),
            process_error_message=row.process_error_message,
            processing_completed_at=row.processing_completed_at,
            periods={
                name: ByTargetPeriodSinglePeriodProcessingState.model_validate(period)
                for name, period in (row.periods or {}).items()
            },
        )

    def write_processing_state(
        self,
        processing_flow_state: ByTargetPeriodProcessingState,
    ) -> None:
        """Upsert the processing state row of the run."""
        self._upsert_rows(
            rows=[
                ByTargetPeriodProcessingStateRow(
                    flow_uid=processing_flow_state.flow_uid,
                    flow_namespace=self.flow_namespace,
                    flow_name=self.flow_name,
                    strategy=processing_flow_state.strategy,
                    granularity=processing_flow_state.granularity,
                    period_timezone=processing_flow_state.period_timezone,
                    week_start=processing_flow_state.week_start,
                    scanned_at=processing_flow_state.scanned_at,
                    processing_status=processing_flow_state.processing_status,
                    process_error_message=processing_flow_state.process_error_message,
                    processing_completed_at=(
                        processing_flow_state.processing_completed_at
                    ),
                    periods={
                        name: period.model_dump(mode="json")
                        for name, period in processing_flow_state.periods.items()
                    },
                    written_at=get_current_datetime(),
                ),
            ],
            table_name=self.processing_state_table_name,
            conflict_fields=["flow_uid"],
            commit=True,
        )

    # ---- Planned state, used through the connector planned-state mixins. ----

    def _create_planned_processing_state_table(self) -> None:
        """Create the by_target_period planned processing-state table if absent.

        Planned-state mixins come first in a backend's MRO and declare the
        abstract ``_ensure_planned_processing_state_table_exists`` hook, so
        each planned-capable backend overrides that hook to call this.
        """
        self.pydantic_manager.create_table(
            model_class=ByTargetPeriodPlannedProcessingStateRow,
            schema_name=self.backend_schema_name,
            table_name=self.planned_processing_state_table_name,
            table_exists="skip",
            track_timestamps=True,
            use_business_key_as_primary=True,
        )

    def write_planned_processing_state(
        self,
        plan_state_uid: str,
        detailed_state: ByTargetPeriodPlannedProcessingDetailedState,
    ) -> None:
        """Persist the planned-state row of a new PLANNED plan."""
        self._upsert_rows(
            rows=[
                ByTargetPeriodPlannedProcessingStateRow(
                    plan_state_uid=plan_state_uid,
                    flow_namespace=self.flow_namespace,
                    flow_name=self.flow_name,
                    strategy=detailed_state.strategy,
                    granularity=detailed_state.granularity,
                    period_timezone=detailed_state.period_timezone,
                    week_start=detailed_state.week_start,
                    scanned_at=detailed_state.scanned_at,
                    periods={
                        name: period.model_dump(mode="json")
                        for name, period in detailed_state.periods.items()
                    },
                ),
            ],
            table_name=self.planned_processing_state_table_name,
            conflict_fields=["plan_state_uid"],
            commit=True,
        )

    def read_planned_processing_state(
        self,
        plan_state_uid: str,
    ) -> ByTargetPeriodPlannedProcessingDetailedState | None:
        """Reconstruct the by_target_period planned detail from its row."""
        rows = cast(
            list[ByTargetPeriodPlannedProcessingStateRow],
            self.pydantic_manager.read_models(
                model_class=ByTargetPeriodPlannedProcessingStateRow,
                schema_name=self.backend_schema_name,
                table_name=self.planned_processing_state_table_name,
                where_conditions={"plan_state_uid": plan_state_uid},
            ),
        )
        if not rows:
            return None
        row = rows[0]
        return ByTargetPeriodPlannedProcessingDetailedState(
            plan_state_uid=row.plan_state_uid,
            strategy=row.strategy,
            granularity=row.granularity,
            period_timezone=row.period_timezone,
            week_start=row.week_start,
            scanned_at=row.scanned_at,
            periods={
                name: PLANNED_PERIOD_CLASS.model_validate(period)
                for name, period in (row.periods or {}).items()
            },
        )
