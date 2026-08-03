import abc
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from nld.connector.s3_blob_storage import S3ObjectStorageConnector
from nld.flow.backend.utils import BackendStandardFolderNames
from nld.flow.incremental.backend.s3_blob_storage import S3IncrementalBackendMixin
from nld.flow.incremental.impl.by_key.backend.base_with_pydantic import (
    ByKeyStateBackendManager,
)
from nld.flow.incremental.impl.by_key.schema import (
    get_by_key_planned_processing_detail_schema,
    get_by_key_processing_state_schema,
)
from nld.flow.incremental.impl.by_key.state import (
    ByKeyPlannedProcessingDetailedState,
    ByKeyProcessingState,
    ByKeySingleKeyPlannedProcessingDetailedState,
    ByKeySingleKeyProcessingState,
    ByKeyState,
)
from nld.utils.datetime_util import COMPACT_DATETIME_FORMAT

S3_BY_KEY_PLANNED_PROCESSING_STATE_BASE_NAME = "by_key_planned_processing_state"
S3_BY_KEY_PLANNED_PROCESSING_STATE_FILE_NAME = (
    f"{S3_BY_KEY_PLANNED_PROCESSING_STATE_BASE_NAME}.json"
)

_ENVELOPE_METADATA_FLOW_UID = b"nld_flow_uid"
_ENVELOPE_METADATA_STRATEGY = b"nld_strategy"


class S3ByKeyBackendStateManagerBase(
    S3IncrementalBackendMixin,
    ByKeyStateBackendManager[S3ObjectStorageConnector],
    abc.ABC,
):
    """
    Base class for S3 by_key state backend managers.

    Combines S3IncrementalBackendMixin functionality with
    ByKeyStateBackendManager for different engine implementations
    (pydantic, duckdb).

    The on-disk encoding of every by_key state file (planned-state,
    in-flight processing state) follows the implementing class's
    ``file_format`` — ``json`` writes the full Pydantic envelope, ``parquet``
    writes a rows table of ``ByKeySingleKeyProcessingState`` with the
    envelope (``flow_uid`` / ``strategy``) carried in parquet schema
    metadata so it round-trips losslessly.
    """

    param_definitions = [*S3IncrementalBackendMixin.s3_param_definitions]

    @property
    @abc.abstractmethod
    def local_processed_state_file_path(self) -> Path:
        """Local path of the in-process processing-state file."""
        ...

    @property
    @abc.abstractmethod
    def local_post_processing_state_file_path(self) -> Path:
        """Local path of the post-processing (general) state file."""
        ...

    @property
    def planned_processing_state_file_name(self) -> str:
        """Name of the per-plan planned-state file (extension matches file_format)."""
        return f"{S3_BY_KEY_PLANNED_PROCESSING_STATE_BASE_NAME}.{self._file_extension}"

    # ---- Per-run processing-state layout next to the run's data folder. ----

    @property
    def processed_state_file_name(self) -> str:
        """Name of the run's processing-state file (extension per file_format)."""
        return self.local_processed_state_file_path.name

    @property
    def _processing_state_remote_path(self) -> str:
        """Remote path of this run's single processing-state file.

        Lives in the run's own state folder (``{s3_root}/<timestamp>/state/``),
        a sibling of that run's ``data/`` folder, so state sits next to data.
        """
        return f"{self.backend_run_state_path}/{self.processed_state_file_name}"

    @property
    def _processing_state_local_path(self) -> Path:
        """Local path mirroring this run's processing-state remote layout."""
        run_dir = self.local_state_dir / self.run_folder_timestamp
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir / self.processed_state_file_name

    def _write_processing_state_single_file(
        self,
        processing_flow_state: ByKeyProcessingState,
        serialize: Callable[[ByKeyProcessingState, Path], None],
    ) -> None:
        """Persist the whole processing state as one file under the run folder.

        All keys are written to a single ``{s3_root}/<timestamp>/state/`` blob —
        the run's own folder — so keys never explode into one blob each and the
        previous runs' folders are left intact as history.
        """
        self._create_local_state_dir()
        local_path = self._processing_state_local_path
        serialize(processing_flow_state, local_path)
        self.backend_connector.upload_file_from_local_path(
            local_file_path=str(local_path),
            obj_storage_path=self._processing_state_remote_path,
        )

    # ---- Read-only accessors used by the `nld flow state` CLI. ----

    def read_processing_state(self) -> ByKeyProcessingState | None:
        """Read back the most recent run's processing state, or None if absent.

        Each run persists ``{s3_root}/<timestamp>/state/processed.<fmt>``; this
        picks the latest run folder so the CLI reflects only the last run.
        """
        remote_path = self._latest_processing_state_remote_path()
        if remote_path is None:
            return None
        self.local_state_dir.mkdir(parents=True, exist_ok=True)
        local_path = self.local_state_dir / self.processed_state_file_name
        self.backend_connector.download_file_to_local_path(
            obj_storage_path=remote_path,
            local_file_path=str(local_path),
        )
        if self.file_format == "parquet":
            return self._read_by_key_processing_state_from_parquet(
                local_path=local_path,
            )
        return ByKeyProcessingState.read_json_file(local_path)

    def _latest_processing_state_remote_path(self) -> str | None:
        """Return the newest ``{s3_root}/<timestamp>/state/processed.<fmt>``.

        Lists the run folders directly under ``s3_root`` (one non-recursive
        listing, so the runs' large ``data/`` folders are not walked), keeps
        those whose name parses as a run timestamp, and returns the processing
        file in the greatest one — or ``None`` when none has been written.
        """
        run_folders = sorted(
            folder
            for folder in self._list_run_folder_names()
            if self._is_run_folder(folder)
        )
        for folder in reversed(run_folders):
            remote_path = (
                f"{self.s3_root_path}/{folder}"
                f"/{BackendStandardFolderNames.STATE}/{self.processed_state_file_name}"
            )
            if self.backend_connector.check_if_file_exists(
                obj_storage_path=remote_path,
            ):
                return remote_path
        return None

    def _list_run_folder_names(self) -> list[str]:
        """List the immediate child folder names directly under ``s3_root``."""
        root = self.s3_root_path.rstrip("/")
        blobs = self.backend_connector._get_blobs_list(prefix=f"{root}/")
        names: list[str] = []
        for blob in blobs:
            name = blob[len(root) :].strip("/").split("/")[0]
            if name:
                names.append(name)
        return names

    @staticmethod
    def _is_run_folder(folder_name: str) -> bool:
        """Whether ``folder_name`` is a compact run timestamp, not a stray folder."""
        try:
            datetime.strptime(folder_name, COMPACT_DATETIME_FORMAT)
        except ValueError:
            return False
        return True

    def read_post_processing_state(self) -> ByKeyState | None:
        """Read the current persisted post-processing state, or None if absent.

        Returns ``None`` when no general-state file exists yet, instead of the
        empty default ``read_current_state`` hands back on a first run.
        """
        remote_path = (
            f"{self.backend_state_root_path}"
            f"/{self.local_post_processing_state_file_path.name}"
        )
        if not self.backend_connector.check_if_file_exists(
            obj_storage_path=remote_path,
        ):
            return None
        return self.read_current_state()

    # ---- S3IncrementalBackendMixin hooks. ----

    def _planned_processing_state_remote_path(self, plan_state_uid: str) -> str:
        return (
            f"{self._plan_folder_prefix(plan_state_uid)}"
            f"/{self.planned_processing_state_file_name}"
        )

    def _planned_processing_state_local_path(self, plan_state_uid: str) -> Path:
        return (
            self._plan_local_dir(plan_state_uid)
            / self.planned_processing_state_file_name
        )

    def write_planned_processing_state(
        self,
        plan_state_uid: str,
        detailed_state: ByKeyPlannedProcessingDetailedState,
    ) -> None:
        """Persist the by_key planned detail as a sibling per-plan file.

        The encoding follows ``file_format``.
        """
        local_path = self._planned_processing_state_local_path(plan_state_uid)
        if self.file_format == "parquet":
            self._write_by_key_planned_detail_to_parquet(
                detail=detailed_state,
                local_path=local_path,
            )
        else:
            with open(local_path, "w") as fp:
                fp.write(detailed_state.model_dump_json(indent=2))
        self.backend_connector.upload_file_from_local_path(
            local_file_path=str(local_path),
            obj_storage_path=self._planned_processing_state_remote_path(plan_state_uid),
        )

    def read_planned_processing_state(
        self,
        plan_state_uid: str,
    ) -> ByKeyPlannedProcessingDetailedState | None:
        """Read back the by_key planned detail from its sibling file."""
        remote_path = self._planned_processing_state_remote_path(plan_state_uid)
        if not self.backend_connector.check_if_file_exists(
            obj_storage_path=remote_path,
        ):
            return None
        local_path = self._planned_processing_state_local_path(plan_state_uid)
        self.backend_connector.download_file_to_local_path(
            obj_storage_path=remote_path,
            local_file_path=str(local_path),
        )
        if self.file_format == "parquet":
            return self._read_by_key_planned_detail_from_parquet(
                local_path=local_path,
            )
        return ByKeyPlannedProcessingDetailedState.read_json_file(local_path)

    # ---- Parquet (de)serialisation for ByKeyProcessingState. ----

    @staticmethod
    def _write_by_key_processing_state_to_parquet(
        state: ByKeyProcessingState,
        local_path: Path,
    ) -> None:
        """Write a ``ByKeyProcessingState`` as a rows-table parquet file.

        The envelope (``flow_uid`` / ``strategy``) is carried in PyArrow
        schema metadata so the file round-trips losslessly without
        duplicating the envelope on every row.
        """
        records = [
            {
                "name": key_state.name,
                "processing_status": key_state.processing_status,
                "process_error_message": key_state.process_error_message,
                "processing_completed_at": key_state.processing_completed_at,
                "parameters": (
                    json.dumps(key_state.parameters) if key_state.parameters else None
                ),
            }
            for key_state in state.keys.values()
        ]
        schema = get_by_key_processing_state_schema().with_metadata(
            {
                _ENVELOPE_METADATA_FLOW_UID: state.flow_uid.encode("utf-8"),
                _ENVELOPE_METADATA_STRATEGY: state.strategy.encode("utf-8"),
            },
        )
        table = pa.Table.from_pylist(records, schema=schema)
        pq.write_table(table, local_path)

    @staticmethod
    def _read_by_key_processing_state_from_parquet(
        local_path: Path,
    ) -> ByKeyProcessingState:
        """Read a ``ByKeyProcessingState`` back from its rows-table parquet form."""
        table = pq.read_table(local_path)
        metadata = table.schema.metadata or {}
        flow_uid = metadata.get(_ENVELOPE_METADATA_FLOW_UID, b"").decode("utf-8")
        strategy = metadata.get(_ENVELOPE_METADATA_STRATEGY, b"").decode("utf-8")
        keys: dict[str, ByKeySingleKeyProcessingState] = {}
        for record in table.to_pylist():
            parameters_str = record.get("parameters")
            parameters = json.loads(parameters_str) if parameters_str else None
            keys[record["name"]] = ByKeySingleKeyProcessingState(
                name=record["name"],
                processing_status=record["processing_status"],
                process_error_message=record.get("process_error_message"),
                processing_completed_at=record.get("processing_completed_at"),
                parameters=parameters,
            )
        return ByKeyProcessingState(
            flow_uid=flow_uid,
            strategy=strategy,
            keys=keys,
        )

    # ---- Parquet (de)serialisation for the planned detail. ----

    @staticmethod
    def _write_by_key_planned_detail_to_parquet(
        detail: ByKeyPlannedProcessingDetailedState,
        local_path: Path,
    ) -> None:
        """Write a ``ByKeyPlannedProcessingDetailedState`` as a rows-table parquet.

        The envelope (``plan_state_uid`` / ``strategy``) is carried in PyArrow
        schema metadata so the file round-trips losslessly.
        """
        records = [
            {
                "name": key_detail.name,
                "planned_processing_status": key_detail.planned_processing_status,
                "parameters": (
                    json.dumps(key_detail.parameters) if key_detail.parameters else None
                ),
            }
            for key_detail in detail.keys.values()
        ]
        schema = get_by_key_planned_processing_detail_schema().with_metadata(
            {
                _ENVELOPE_METADATA_FLOW_UID: detail.plan_state_uid.encode("utf-8"),
                _ENVELOPE_METADATA_STRATEGY: detail.strategy.encode("utf-8"),
            },
        )
        table = pa.Table.from_pylist(records, schema=schema)
        pq.write_table(table, local_path)

    @staticmethod
    def _read_by_key_planned_detail_from_parquet(
        local_path: Path,
    ) -> ByKeyPlannedProcessingDetailedState:
        """Read a ``ByKeyPlannedProcessingDetailedState`` back from parquet."""
        table = pq.read_table(local_path)
        metadata = table.schema.metadata or {}
        plan_state_uid = metadata.get(_ENVELOPE_METADATA_FLOW_UID, b"").decode("utf-8")
        strategy = metadata.get(_ENVELOPE_METADATA_STRATEGY, b"").decode("utf-8")
        keys: dict[str, ByKeySingleKeyPlannedProcessingDetailedState] = {}
        for record in table.to_pylist():
            parameters_str = record.get("parameters")
            parameters = json.loads(parameters_str) if parameters_str else None
            keys[record["name"]] = ByKeySingleKeyPlannedProcessingDetailedState(
                name=record["name"],
                planned_processing_status=record["planned_processing_status"],
                parameters=parameters,
            )
        return ByKeyPlannedProcessingDetailedState(
            plan_state_uid=plan_state_uid,
            strategy=strategy,
            keys=keys,
        )
