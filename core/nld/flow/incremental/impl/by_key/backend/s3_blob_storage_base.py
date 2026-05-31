import abc
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from nld.connector.s3_blob_storage import S3ObjectStorageConnector
from nld.flow.incremental.backend.s3_blob_storage import S3IncrementalBackendMixin
from nld.flow.incremental.impl.by_key.backend.base_with_pydantic import (
    ByKeyStateBackendManager,
)
from nld.flow.incremental.impl.by_key.schema import (
    get_by_key_processing_state_schema,
)
from nld.flow.incremental.impl.by_key.state import (
    ByKeyProcessingState,
    ByKeySingleKeyProcessingState,
    ByKeyState,
)
from nld.flow.incremental.models import FlowProcessingState

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

    # ---- Read-only accessors used by the `nld flow state` CLI. ----

    def read_processing_state(self) -> ByKeyProcessingState | None:
        """Read the current persisted processing state, or None if absent.

        The processing-state file uses the same ``file_format`` as the rest
        of the backend; this dispatcher hides the encoding from callers.
        """
        remote_path = (
            f"{self.backend_state_for_processing_path}"
            f"/{self.local_processed_state_file_path.name}"
        )
        if not self.backend_connector.check_if_file_exists(
            obj_storage_path=remote_path,
        ):
            return None
        self.backend_connector.download_file_to_local_path(
            obj_storage_path=remote_path,
            local_file_path=str(self.local_processed_state_file_path),
        )
        if self.file_format == "parquet":
            return self._read_by_key_processing_state_from_parquet(
                local_path=self.local_processed_state_file_path,
            )
        return ByKeyProcessingState.read_json_file(
            self.local_processed_state_file_path,
        )

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
        processing_state: FlowProcessingState,
    ) -> None:
        """Persist the by_key processing state as a sibling per-plan file.

        Rewrites ``processing_state.flow_uid`` to ``plan_state_uid`` so the
        on-disk payload doesn't carry the transient executor UUID from
        compute time — the consumer assigns the real ``flow_uid`` at
        hydration. The encoding follows ``file_format``.
        """
        plan_payload = processing_state.model_copy(
            update={"flow_uid": plan_state_uid},
        )
        local_path = self._planned_processing_state_local_path(plan_state_uid)
        if self.file_format == "parquet":
            self._write_by_key_processing_state_to_parquet(
                state=plan_payload,  # type: ignore[arg-type]
                local_path=local_path,
            )
        else:
            with open(local_path, "w") as fp:
                fp.write(plan_payload.model_dump_json(indent=2))
        self.backend_connector.upload_file_from_local_path(
            local_file_path=str(local_path),
            obj_storage_path=self._planned_processing_state_remote_path(plan_state_uid),
        )

    def read_planned_processing_state(
        self,
        plan_state_uid: str,
    ) -> ByKeyProcessingState | None:
        """Read back the by_key processing state from its sibling file."""
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
            return self._read_by_key_processing_state_from_parquet(
                local_path=local_path
            )
        return ByKeyProcessingState.read_json_file(local_path)

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
