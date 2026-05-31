from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from nld.flow.backend.s3_blob_storage import S3BackendMixin
from nld.flow.incremental.backend.plan import (
    BackendStatePlanRow,
    row_to_state_plan,
    state_plan_to_row,
)
from nld.flow.incremental.backend.s3_blob_storage.schema import (
    get_state_plans_index_schema,
)
from nld.flow.incremental.models import FlowStatePlan

STATE_PLANS_SUB_FOLDER = "plans"
STATE_PLANS_INDEX_BASE_NAME = "state_plans"
STATE_PLANS_INDEX_FILE_NAME = f"{STATE_PLANS_INDEX_BASE_NAME}.json"


class S3IncrementalBackendMixin(S3BackendMixin):
    """Connector-specific planned-state persistence for S3.

    Owns only the I/O for the single state-plans index file at
    ``<state-root>/state_plans.{json|parquet}``: write, read and list state
    plans. The index is a collection keyed by ``plan_state_uid`` carrying the
    backend-agnostic ``BackendStatePlanRow`` payload for every plan known
    to this flow's state root — so one S3 GET serves every list/lookup
    call regardless of plan history length.

    The on-disk encoding follows the implementing class's ``file_format``
    (``json`` or ``parquet``); both formats are loaded and stored through
    the same ``_load_state_plans_index`` / ``_save_state_plans_index``
    entry points.

    The generic plan lifecycle (cancel-on-supersede, COMPLETED /
    CANCELLED transitions, latest-PLANNED selection) lives in
    ``IncrementalStateManager``. Per-strategy backends write the
    strategy-specific processing-state payload into a sibling per-plan
    file under ``<state-root>/plans/<plan_state_uid>/`` through the
    ``write_planned_processing_state`` / ``read_planned_processing_state``
    hooks — those files stay per-plan because they can be large
    (per-key state for ``by_key``) and are only hydrated on demand.

    Extends ``S3BackendMixin`` so the implementing class automatically
    inherits ``backend_connector`` / ``parameters`` /
    ``backend_state_root_path`` / ``local_state_dir`` and only needs to
    bring in the incremental plumbing.

    Requires from the implementing class:
      - ``flow_namespace: str``, ``flow_name: str``
      - ``file_format: str`` (already required by ``S3BackendMixin``)

    Concurrency: ``write_state_plan`` performs a read-modify-write on
    the index file and assumes a single writer per flow. The
    planned-state lifecycle already serialises writes through
    ``IncrementalStateManager`` (cancel-on-supersede reads every
    plan, transitions them, then writes the new one), so this matches
    the existing invariant. Multi-writer support would require
    etag-based optimistic concurrency on the index file.
    """

    flow_namespace: str
    flow_name: str

    # S3 persists the state-plans index plus per-plan processing-state
    # files, so every backend built on this mixin can hold a plan.
    supports_planned_state = True

    # ---- Folder / path helpers shared with subclasses. ----

    @property
    def _plans_prefix(self) -> str:
        return f"{self.backend_state_root_path}/{STATE_PLANS_SUB_FOLDER}"

    def _plan_folder_prefix(self, plan_state_uid: str) -> str:
        return f"{self._plans_prefix}/{plan_state_uid}"

    def _plan_local_dir(self, plan_state_uid: str) -> Path:
        path = self.local_state_dir / STATE_PLANS_SUB_FOLDER / plan_state_uid
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def _file_extension(self) -> str:
        """Return the file extension matching ``file_format`` (json or parquet)."""
        return "parquet" if self.file_format == "parquet" else "json"

    @property
    def state_plans_index_file_name(self) -> str:
        """Return the index file name with the extension matching ``file_format``."""
        return f"{STATE_PLANS_INDEX_BASE_NAME}.{self._file_extension}"

    @property
    def _state_plans_index_remote_path(self) -> str:
        return f"{self.backend_state_root_path}/{self.state_plans_index_file_name}"

    @property
    def _state_plans_index_local_path(self) -> Path:
        self.local_state_dir.mkdir(parents=True, exist_ok=True)
        return self.local_state_dir / self.state_plans_index_file_name

    # ---- State-plan persistence primitives. ----

    def read_state_plan(
        self,
        plan_state_uid: str,
    ) -> FlowStatePlan | None:
        """Return the state plan for ``plan_state_uid`` scoped to this flow."""
        index = self._load_state_plans_index()
        row = index.get(plan_state_uid)
        if row is None:
            return None
        if row.flow_namespace != self.flow_namespace:
            return None
        if row.flow_name != self.flow_name:
            return None
        return row_to_state_plan(row=row)

    def read_state_plans(
        self,
    ) -> list[FlowStatePlan]:
        """Return every state plan for this flow, any status."""
        index = self._load_state_plans_index()
        return [
            row_to_state_plan(row=row)
            for row in index.values()
            if row.flow_namespace == self.flow_namespace
            and row.flow_name == self.flow_name
        ]

    def write_state_plan(
        self,
        state_plan: FlowStatePlan,
    ) -> None:
        """Upsert a single state plan into the index file.

        Reads the current index, replaces the row for
        ``state_plan.plan_state_uid``, and rewrites the file. Single-writer
        per flow is assumed — see the class docstring.
        """
        index = self._load_state_plans_index()
        index[state_plan.plan_state_uid] = state_plan_to_row(state_plan=state_plan)
        self._save_state_plans_index(index=index)

    # ---- Internal index-file helpers. ----

    def _load_state_plans_index(self) -> dict[str, BackendStatePlanRow]:
        """Download and parse the state-plans index, or return an empty map.

        Dispatches on ``file_format``: JSON uses ``json.load``; parquet uses
        PyArrow against the ``BackendStatePlanRow``-derived schema.
        """
        remote_path = self._state_plans_index_remote_path
        if not self.backend_connector.check_if_file_exists(
            obj_storage_path=remote_path,
        ):
            return {}
        local_path = self._state_plans_index_local_path
        self.backend_connector.download_file_to_local_path(
            obj_storage_path=remote_path,
            local_file_path=str(local_path),
        )
        if self.file_format == "parquet":
            return self._read_state_plans_index_from_parquet(local_path=local_path)
        return self._read_state_plans_index_from_json(local_path=local_path)

    def _save_state_plans_index(
        self,
        index: dict[str, BackendStatePlanRow],
    ) -> None:
        """Serialise the index map to ``file_format`` and upload it."""
        local_path = self._state_plans_index_local_path
        if self.file_format == "parquet":
            self._write_state_plans_index_to_parquet(
                index=index,
                local_path=local_path,
            )
        else:
            self._write_state_plans_index_to_json(
                index=index,
                local_path=local_path,
            )
        self.backend_connector.upload_file_from_local_path(
            local_file_path=str(local_path),
            obj_storage_path=self._state_plans_index_remote_path,
        )

    @staticmethod
    def _read_state_plans_index_from_json(
        local_path: Path,
    ) -> dict[str, BackendStatePlanRow]:
        with open(local_path) as fp:
            payload = json.load(fp)
        return {
            uid: BackendStatePlanRow.model_validate(row_payload)
            for uid, row_payload in payload.items()
        }

    @staticmethod
    def _write_state_plans_index_to_json(
        index: dict[str, BackendStatePlanRow],
        local_path: Path,
    ) -> None:
        payload = {uid: json.loads(row.model_dump_json()) for uid, row in index.items()}
        with open(local_path, "w") as fp:
            json.dump(payload, fp, indent=2)

    @staticmethod
    def _read_state_plans_index_from_parquet(
        local_path: Path,
    ) -> dict[str, BackendStatePlanRow]:
        table = pq.read_table(local_path)
        rows: dict[str, BackendStatePlanRow] = {}
        for record in table.to_pylist():
            row = BackendStatePlanRow.model_validate(record)
            rows[row.plan_state_uid] = row
        return rows

    @staticmethod
    def _write_state_plans_index_to_parquet(
        index: dict[str, BackendStatePlanRow],
        local_path: Path,
    ) -> None:
        records = [row.model_dump() for row in index.values()]
        table = pa.Table.from_pylist(
            records,
            schema=get_state_plans_index_schema(),
        )
        pq.write_table(table, local_path)
