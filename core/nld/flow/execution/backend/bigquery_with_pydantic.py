from typing import Any, cast

from nld.connector.bigquery.bigquery_connector import BigQueryConnector
from nld.flow.backend.bigquery.backend_mixin import BigQueryBackendMixin
from nld.flow.backend.bigquery.utils import BIGQUERY_BACKEND_TABLE_PREFIX
from nld.flow.execution.events import ExecutionBackendEngineInitialized
from nld.flow.execution.execution_info import (
    FlowExecutionHistory,
    FlowExecutionInfo,
    FlowExecutionState,
    FlowStepExecutionInfo,
)
from nld.flow.execution.manager import (
    ExecutionBackendStateManager,
)
from nld.flow.execution.utils import (
    EXECUTION_HISTORY_NAME,
    EXECUTION_STATE_NAME,
    EXECUTION_STEP_HISTORY_NAME,
)

BIGQUERY_EXECUTION_HISTORY_TABLE_NAME = (
    f"{BIGQUERY_BACKEND_TABLE_PREFIX}_{EXECUTION_HISTORY_NAME}"
)
BIGQUERY_EXECUTION_STATE_TABLE_NAME = (
    f"{BIGQUERY_BACKEND_TABLE_PREFIX}_{EXECUTION_STATE_NAME}"
)
BIGQUERY_EXECUTION_STEP_HISTORY_TABLE_NAME = (
    f"{BIGQUERY_BACKEND_TABLE_PREFIX}_{EXECUTION_STEP_HISTORY_NAME}"
)


class BigQueryExecutionBackendStateManager(
    BigQueryBackendMixin,
    ExecutionBackendStateManager[BigQueryConnector],
):
    """
    Execution - BigQuery - Backend State Manager

    Manages all read and write methods for execution state using BigQuery.
    """

    _EXCLUDE_FIELDS: set[str] = {"steps"}

    param_definitions = []

    def __init__(
        self,
        backend_connector: BigQueryConnector,
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

        self.flow_name = flow_name

        self.pydantic_manager = self.backend_connector.get_model_manager()

        self._ensure_tables_exist()

        self.log_event(
            ExecutionBackendEngineInitialized(
                backend_type=backend_connector.connection_wrapper.type,
                engine="pydantic",
                manager_class=type(self).__name__,
            ),
        )

    def _ensure_tables_exist(self) -> None:
        self.pydantic_manager.create_table(
            model_class=FlowExecutionInfo,
            schema_name=self.backend_schema_name,
            table_name=BIGQUERY_EXECUTION_HISTORY_TABLE_NAME,
            table_exists="skip",
            exclude_fields=self._EXCLUDE_FIELDS,
            track_timestamps=True,
        )

        self.pydantic_manager.create_table(
            model_class=FlowExecutionInfo,
            schema_name=self.backend_schema_name,
            table_name=BIGQUERY_EXECUTION_STATE_TABLE_NAME,
            table_exists="skip",
            use_functional_key_as_primary=True,
            exclude_fields=self._EXCLUDE_FIELDS,
            track_timestamps=True,
        )

        self.pydantic_manager.create_table(
            model_class=FlowStepExecutionInfo,
            schema_name=self.backend_schema_name,
            table_name=BIGQUERY_EXECUTION_STEP_HISTORY_TABLE_NAME,
            table_exists="skip",
            track_timestamps=True,
        )

    def _get_execution_state_from_db(self) -> FlowExecutionState | None:
        execution_info = cast(
            FlowExecutionInfo,
            self.pydantic_manager.read_model(
                model_class=FlowExecutionInfo,
                schema_name=self.backend_schema_name,
                table_name=BIGQUERY_EXECUTION_STATE_TABLE_NAME,
                where_conditions={
                    "flow_namespace": self.flow_namespace,
                    "flow_name": self.flow_name,
                },
                exclude_fields=self._EXCLUDE_FIELDS,
            ),
        )

        return FlowExecutionState(last_processed=execution_info)

    def _get_execution_history_from_db(self) -> FlowExecutionHistory:
        execution_infos = cast(
            list[FlowExecutionInfo],
            self.pydantic_manager.read_models(
                model_class=FlowExecutionInfo,
                schema_name=self.backend_schema_name,
                table_name=BIGQUERY_EXECUTION_HISTORY_TABLE_NAME,
                where_conditions={
                    "flow_namespace": self.flow_namespace,
                    "flow_name": self.flow_name,
                },
                order_by=["-started_at"],
                exclude_fields=self._EXCLUDE_FIELDS,
            ),
        )

        return FlowExecutionHistory(executions=execution_infos)

    def retrieve_latest_execution_state(
        self,
    ) -> tuple[FlowExecutionState, FlowExecutionHistory]:
        execution_state = self._get_execution_state_from_db()
        execution_history = self._get_execution_history_from_db()

        if execution_state is None:
            execution_state = FlowExecutionState(last_processed=None)

        return execution_state, execution_history

    def save_execution_info_start(
        self,
        current_execution_info: FlowExecutionInfo,
    ) -> None:
        """Save execution info header at the start of execution."""
        self.pydantic_manager.upsert_model(
            model=current_execution_info,
            schema_name=self.backend_schema_name,
            table_name=BIGQUERY_EXECUTION_HISTORY_TABLE_NAME,
            conflict_fields=["flow_uid"],
            commit=True,
            exclude_fields=self._EXCLUDE_FIELDS,
            track_timestamps=True,
        )

    def save_step_info(
        self,
        step_info: FlowStepExecutionInfo,
    ) -> None:
        """Save a single completed step to BigQuery."""
        self.pydantic_manager.insert_model(
            model=step_info,
            schema_name=self.backend_schema_name,
            table_name=BIGQUERY_EXECUTION_STEP_HISTORY_TABLE_NAME,
            commit=True,
            track_timestamps=True,
        )

    def save_execution_info(
        self,
        current_execution_info: FlowExecutionInfo,
        saved_step_names: list[str] | None = None,
    ) -> None:
        """Save the current execution info row + step rows to BigQuery."""
        self.pydantic_manager.upsert_model(
            model=current_execution_info,
            schema_name=self.backend_schema_name,
            table_name=BIGQUERY_EXECUTION_HISTORY_TABLE_NAME,
            conflict_fields=["flow_uid"],
            commit=False,
            exclude_fields=self._EXCLUDE_FIELDS,
            track_timestamps=True,
        )

        if current_execution_info.steps:
            already_saved = set(saved_step_names or [])
            for step in current_execution_info.steps:
                if step.step_name not in already_saved:
                    self.pydantic_manager.insert_model(
                        model=step,
                        schema_name=self.backend_schema_name,
                        table_name=BIGQUERY_EXECUTION_STEP_HISTORY_TABLE_NAME,
                        commit=False,
                        track_timestamps=True,
                    )

    def save_execution_state(
        self,
        current_execution_info: FlowExecutionInfo | None = None,
        new_execution_state: FlowExecutionState | None = None,
    ) -> None:
        """Save the execution state record to BigQuery."""
        state_info = current_execution_info
        if (
            new_execution_state is not None
            and new_execution_state.last_processed is not None
        ):
            state_info = new_execution_state.last_processed
        assert state_info is not None
        self.pydantic_manager.upsert_model(
            model=state_info,
            schema_name=self.backend_schema_name,
            table_name=BIGQUERY_EXECUTION_STATE_TABLE_NAME,
            conflict_fields=["flow_namespace", "flow_name"],
            commit=False,
            exclude_fields=self._EXCLUDE_FIELDS,
            track_timestamps=True,
        )
