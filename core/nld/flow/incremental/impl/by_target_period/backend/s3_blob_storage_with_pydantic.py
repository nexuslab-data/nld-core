from pathlib import Path
from typing import Any

from nld.connector.s3_blob_storage import S3ObjectStorageConnector
from nld.flow.backend.s3_blob_storage import S3BackendMixin
from nld.flow.incremental.backend.s3_blob_storage import S3IncrementalBackendMixin
from nld.flow.incremental.impl.by_target_period.backend.base_with_pydantic import (
    ByTargetPeriodStateBackendManager,
)
from nld.flow.incremental.impl.by_target_period.constants import (
    GENERAL_STATE_NAME,
    PLANNED_PROCESSING_STATE_NAME,
    PROCESSED_STATE_NAME,
)
from nld.flow.incremental.impl.by_target_period.schema import (
    read_period_rows_from_parquet,
    write_period_rows_to_parquet,
)
from nld.flow.incremental.impl.by_target_period.state import (
    ByTargetPeriodPlannedProcessingDetailedState,
    ByTargetPeriodProcessingState,
    ByTargetPeriodSinglePeriodPlannedProcessingDetailedState,
    ByTargetPeriodSinglePeriodProcessingState,
    ByTargetPeriodSinglePeriodState,
    ByTargetPeriodState,
)
from nld.flow.incremental.models.events import (
    IncrementalBackendEngineInitialized,
)
from nld.parameters import ExecutionParameterDefinition
from nld.pydantic import NldBaseModel


class S3ByTargetPeriodPydanticStateBackendManager(
    S3IncrementalBackendMixin,
    ByTargetPeriodStateBackendManager[S3ObjectStorageConnector],
):
    """
    Incremental - By Target Period - S3 - Backend State Manager

    Persists the by_target_period state as files on object storage, in the
    S3 layout shared by every incremental type:

    - ``{s3_root}/state/period_state.<fmt>`` — the authoritative state;
    - ``{s3_root}/<run timestamp>/state/period_processed_state.<fmt>`` —
      each run's processing state, next to that run's data folder;
    - ``{s3_root}/state/plans/<plan uid>/...`` — the PLANNED plans, indexed
      by ``S3IncrementalBackendMixin``.

    ``file_format`` is ``json`` (whole Pydantic documents) or ``parquet``
    (one row per period, the other fields in the schema metadata).
    """

    param_definitions = [
        *S3BackendMixin.s3_param_definitions,
        ExecutionParameterDefinition(name="s3_root_path", mandatory=True),
        ExecutionParameterDefinition(
            name="file_format",
            mandatory=False,
            default_value="json",
            allowed_values=["json", "parquet"],
            help_text="Storage format: 'json' or 'parquet'",
        ),
    ]

    def __init__(
        self,
        backend_connector: S3ObjectStorageConnector,
        flow_namespace: str,
        flow_name: str,
        parameters: dict[str, Any],
        **kwargs: Any,
    ):
        super().__init__(
            backend_connector=backend_connector,
            flow_namespace=flow_namespace,
            flow_name=flow_name,
            parameters=parameters,
            **kwargs,
        )
        self.log_event(
            IncrementalBackendEngineInitialized(
                backend_type=backend_connector.connection_wrapper.type,
                engine="pydantic",
                manager_class=type(self).__name__,
            ),
        )

    @property
    def file_format(self) -> str:
        """Get the storage format (json or parquet)."""
        return self.parameters["file_format"]  # type: ignore[no-any-return]

    @property
    def general_state_file_name(self) -> str:
        return f"{GENERAL_STATE_NAME}.{self._file_extension}"

    @property
    def processed_state_file_name(self) -> str:
        return f"{PROCESSED_STATE_NAME}.{self._file_extension}"

    @property
    def planned_processing_state_file_name(self) -> str:
        return f"{PLANNED_PROCESSING_STATE_NAME}.{self._file_extension}"

    @property
    def _general_state_remote_path(self) -> str:
        return f"{self.backend_state_root_path}/{self.general_state_file_name}"

    def _download(self, remote_path: str, file_name: str) -> Path | None:
        """Download a state file to the local state folder, None if absent."""
        if not self.backend_connector.check_if_file_exists(
            obj_storage_path=remote_path,
        ):
            return None
        self._create_local_state_dir()
        local_path = self.local_state_dir / file_name
        self.backend_connector.download_file_to_local_path(
            obj_storage_path=remote_path,
            local_file_path=str(local_path),
        )
        return local_path

    def _write_document(
        self,
        document: NldBaseModel,
        rows: list[NldBaseModel],
        row_class: type[NldBaseModel],
        rows_field: str,
        local_path: Path,
    ) -> None:
        """Write a state document in the configured ``file_format``.

        JSON keeps the whole document; parquet writes ``rows`` as a table
        and every other field of the document as the envelope.
        """
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if self.file_format != "parquet":
            document.write_json_file(file_path=local_path)
            return
        write_period_rows_to_parquet(
            rows=rows,
            row_class=row_class,
            envelope=document.model_dump(
                mode="json",
                exclude={rows_field},
            ),
            local_path=local_path,
        )

    def _read_document[DOCUMENT: NldBaseModel](
        self,
        document_class: type[DOCUMENT],
        rows_field: str,
        local_path: Path,
    ) -> DOCUMENT:
        """Read a document written by ``_write_document``."""
        if self.file_format != "parquet":
            return document_class.model_validate_json(
                local_path.read_text(encoding="utf-8"),
            )
        rows, envelope = read_period_rows_from_parquet(local_path=local_path)
        return document_class.model_validate(
            {
                **envelope,
                rows_field: {row["name"]: row for row in rows},
            }
        )

    # ---- Authoritative state. ----

    def read_current_state(self) -> ByTargetPeriodState:
        """Retrieve the current period state, empty on a first run."""
        state = self.read_post_processing_state()
        return state if state is not None else ByTargetPeriodState()

    def read_post_processing_state(self) -> ByTargetPeriodState | None:
        """Read the persisted state, None when it was never written."""
        local_path = self._download(
            remote_path=self._general_state_remote_path,
            file_name=self.general_state_file_name,
        )
        if local_path is None:
            return None
        return self._read_document(
            document_class=ByTargetPeriodState,
            rows_field="periods",
            local_path=local_path,
        )

    def write_post_processing_state(
        self,
        post_processing_flow_state: ByTargetPeriodState,
    ) -> None:
        """Write the state file and upload it to the state root folder."""
        local_path = self.local_state_dir / self.general_state_file_name
        self._write_document(
            document=post_processing_flow_state,
            rows=list(post_processing_flow_state.periods.values()),
            row_class=ByTargetPeriodSinglePeriodState,
            rows_field="periods",
            local_path=local_path,
        )
        self._upload_file_to_state_root(local_path=local_path)

    # ---- Processing state, one file per run next to the run's data. ----

    def read_processing_state(self) -> ByTargetPeriodProcessingState | None:
        """Read back the most recent run's processing state, None if absent."""
        remote_path = self._latest_run_state_file_remote_path(
            file_name=self.processed_state_file_name,
        )
        if remote_path is None:
            return None
        local_path = self._download(
            remote_path=remote_path,
            file_name=self.processed_state_file_name,
        )
        if local_path is None:
            return None
        return self._read_document(
            document_class=ByTargetPeriodProcessingState,
            rows_field="periods",
            local_path=local_path,
        )

    def write_processing_state(
        self,
        processing_flow_state: ByTargetPeriodProcessingState,
    ) -> None:
        """Write the run's processing state into the run's own state folder."""
        local_path = (
            self.local_state_dir
            / self.run_folder_timestamp
            / self.processed_state_file_name
        )
        self._write_document(
            document=processing_flow_state,
            rows=list(processing_flow_state.periods.values()),
            row_class=ByTargetPeriodSinglePeriodProcessingState,
            rows_field="periods",
            local_path=local_path,
        )
        self._upload_file_to_run_state_folder(local_path=local_path)

    # ---- S3IncrementalBackendMixin hooks. ----

    def _planned_processing_state_remote_path(self, plan_state_uid: str) -> str:
        return (
            f"{self._plan_folder_prefix(plan_state_uid)}"
            f"/{self.planned_processing_state_file_name}"
        )

    def write_planned_processing_state(
        self,
        plan_state_uid: str,
        detailed_state: ByTargetPeriodPlannedProcessingDetailedState,
    ) -> None:
        """Persist the planned detail as a per-plan file."""
        local_path = (
            self._plan_local_dir(plan_state_uid)
            / self.planned_processing_state_file_name
        )
        self._write_document(
            document=detailed_state,
            rows=list(detailed_state.periods.values()),
            row_class=ByTargetPeriodSinglePeriodPlannedProcessingDetailedState,
            rows_field="periods",
            local_path=local_path,
        )
        self.backend_connector.upload_file_from_local_path(
            local_file_path=str(local_path),
            obj_storage_path=self._planned_processing_state_remote_path(plan_state_uid),
        )

    def read_planned_processing_state(
        self,
        plan_state_uid: str,
    ) -> ByTargetPeriodPlannedProcessingDetailedState | None:
        """Read back the planned detail of a plan, None if absent."""
        remote_path = self._planned_processing_state_remote_path(plan_state_uid)
        if not self.backend_connector.check_if_file_exists(
            obj_storage_path=remote_path,
        ):
            return None
        local_path = (
            self._plan_local_dir(plan_state_uid)
            / self.planned_processing_state_file_name
        )
        self.backend_connector.download_file_to_local_path(
            obj_storage_path=remote_path,
            local_file_path=str(local_path),
        )
        return self._read_document(
            document_class=ByTargetPeriodPlannedProcessingDetailedState,
            rows_field="periods",
            local_path=local_path,
        )
