from typing import Any, cast

from nld.connector.base.connector import DataConnector
from nld.flow.incremental.base.manager import (
    IncrementalBackendStateManager,
    IncrementalStateManager,
)
from nld.flow.incremental.base.sql_filter_manager import IncrementalSqlFilterManager
from nld.flow.incremental.impl.by_key.sql_filter_manager import ByKeySqlFilterManager
from nld.flow.incremental.models import (
    IncrementalProcessingStatus,
    IncrementalStateStatus,
)
from nld.flow.utils import FlowLoadingStrategies

from .logic import (
    BY_KEY_FLOW_INCREMENTAL_LOGIC,
    ByKeyFlowIncrementalParams,
)
from .state import (
    ByKeyPlannedProcessingDetailedState,
    ByKeyPlannedProcessingState,
    ByKeyProcessingState,
    ByKeySingleKeyProcessingState,
    ByKeySingleKeyState,
    ByKeySourceState,
    ByKeyState,
)


class ByKeyStateManager(
    IncrementalStateManager[
        ByKeyState,
        ByKeySourceState,
        ByKeyProcessingState,
        ByKeyPlannedProcessingState,
        ByKeyFlowIncrementalParams,
    ]
):
    flow_incremental_logic = BY_KEY_FLOW_INCREMENTAL_LOGIC

    def __init__(
        self,
        incremental_parameters: ByKeyFlowIncrementalParams,
        incremental_state_backend_manager: IncrementalBackendStateManager[
            DataConnector[Any],
            ByKeyState,
            ByKeySourceState,
            ByKeyProcessingState,
            ByKeyPlannedProcessingState,
            ByKeyPlannedProcessingDetailedState,
        ]
        | None = None,
        secondary_incremental_state_backend_manager: IncrementalBackendStateManager[
            DataConnector[Any],
            ByKeyState,
            ByKeySourceState,
            ByKeyProcessingState,
            ByKeyPlannedProcessingState,
            ByKeyPlannedProcessingDetailedState,
        ]
        | None = None,
        parameters: dict[str, Any] | None = None,
    ):
        super().__init__(
            incremental_parameters=incremental_parameters,
            incremental_state_backend_manager=incremental_state_backend_manager,
            secondary_incremental_state_backend_manager=(
                secondary_incremental_state_backend_manager
            ),
            parameters=parameters,
        )
        self.processing_state: ByKeyProcessingState

    def _supports_partial_state(self) -> bool:
        return True

    def is_planned_processing_state_fresh(
        self,
        planned_processing_state: ByKeyPlannedProcessingState,
    ) -> bool:
        """A by_key plan is always fresh for now.

        A plan may legitimately re-request a key that a later run already
        processed, so the baseline state cannot make a key plan stale.
        """
        return True

    @property
    def sql_filter_manager(self) -> IncrementalSqlFilterManager:
        """Return the key-based SQL filter."""
        return ByKeySqlFilterManager(
            processing_state=self.processing_state,
        )

    def init_processing_state(self) -> None:
        self.processing_state = ByKeyProcessingState(
            flow_uid=self.flow_uid,
            keys={},
            strategy=self.strategy,
        )

    def update_processing_state(self) -> None:
        """
        Determine processing state based on incremental and source state.

        Keys to consider are determined with the following rule:
        - Key latest incremental should not have a terminal status
          (SUCCEEDED or PERMANENTLY_EXCLUDED)
        - Key should be in source state (in the list of keys to be retrieved)

        FULL and explicit-keys BACKFILL re-attempt terminal keys on purpose:
        they are the resurrection paths for PERMANENTLY_EXCLUDED entries.
        """
        assert self.source_state is not None
        self.incremental_parameters: ByKeyFlowIncrementalParams
        if self.strategy in [FlowLoadingStrategies.DELTA]:
            assert self.latest_incremental_state is not None
            terminal_keys = self.latest_incremental_state.get_terminal_keys()
            for key, flow_source_state in self.source_state.keys.items():
                if key not in terminal_keys:
                    flow_processing_state = ByKeySingleKeyProcessingState(
                        name=key,
                        parameters=flow_source_state.parameters,
                        processing_status=IncrementalProcessingStatus.TO_BE_PROCESSED,
                    )
                    self.processing_state.keys.update({key: flow_processing_state})
        elif self.strategy in [FlowLoadingStrategies.BACKFILL_DELTA]:
            assert self.latest_incremental_state is not None
            terminal_keys = self.latest_incremental_state.get_terminal_keys()
            self._apply_backfill_filtering(exclude_keys=terminal_keys)
        elif self.strategy in [FlowLoadingStrategies.BACKFILL]:
            self._apply_backfill_filtering(exclude_keys=None)
        elif self.strategy in [FlowLoadingStrategies.FULL]:
            for key, flow_source_state in self.source_state.keys.items():
                flow_processing_state = ByKeySingleKeyProcessingState(
                    name=key,
                    parameters=flow_source_state.parameters,
                    processing_status=IncrementalProcessingStatus.TO_BE_PROCESSED,
                )
                self.processing_state.keys.update({key: flow_processing_state})
        else:
            raise NotImplementedError(
                f"The method 'update_processing_state' is not implemented "
                f"for data load strategy {self.strategy}"
            )

    def _apply_backfill_filtering(
        self,
        exclude_keys: dict[str, Any] | None,
    ) -> None:
        """Apply backfill key filtering with optional delta exclusion.

        Args:
            exclude_keys: If provided, keys in this dict are excluded from
                processing (used by BACKFILL_DELTA to skip keys with a
                terminal status — SUCCEEDED or PERMANENTLY_EXCLUDED).
        """
        assert self.source_state is not None

        if self.incremental_parameters.limit is not None:
            for key, flow_source_state in self.source_state.keys.items():
                flow_processing_state = ByKeySingleKeyProcessingState(
                    name=key,
                    parameters=flow_source_state.parameters,
                    processing_status=IncrementalProcessingStatus.EXCLUDED,
                )
                self.processing_state.keys.update({key: flow_processing_state})
            if self.incremental_parameters.limit > 0:
                count = 0
                for processing_state in self.processing_state.keys.values():
                    if (
                        processing_state.excluded()
                        and count < self.incremental_parameters.limit
                    ):
                        if (
                            exclude_keys is None
                            or processing_state.name not in exclude_keys
                        ):
                            processing_state.set_to_be_processed()
                            count += 1

        if self.incremental_parameters.keys is not None:
            for key, flow_source_state in self.source_state.keys.items():
                flow_processing_state = ByKeySingleKeyProcessingState(
                    name=key,
                    parameters=flow_source_state.parameters,
                    processing_status=IncrementalProcessingStatus.EXCLUDED,
                )
                self.processing_state.keys.update({key: flow_processing_state})
            for key in self.incremental_parameters.keys:
                if self.processing_state.has_key(key):
                    should_exclude = exclude_keys is not None and key in exclude_keys
                    if not should_exclude:
                        self.processing_state.keys[key].set_to_be_processed()
                else:
                    self.log_warn(
                        f"No key found: {key}. "
                        "This key will not be included in the backfill."
                    )

    def _update_post_processing_from_processing_state_for_single_key(
        self,
        key_name: str,
    ) -> None:
        """Update post-processing state for a single key."""
        assert self.post_processing_state is not None
        processing_state = self.processing_state.keys[key_name]

        # --- Step 1 / Determine post-processing status from processing
        if processing_state.succeeded():
            post_processing_status = IncrementalStateStatus.SUCCEEDED
        elif processing_state.failed():
            post_processing_status = IncrementalStateStatus.FAILED
        elif processing_state.permanently_excluded():
            post_processing_status = IncrementalStateStatus.PERMANENTLY_EXCLUDED
        else:
            post_processing_status = IncrementalStateStatus.NOT_PROCESSED

        # --- Step 2 / Update post-processing state (update or add)
        if self.post_processing_state.has_key(key_name):
            state = self.post_processing_state.keys[key_name]
            if post_processing_status == IncrementalStateStatus.NOT_PROCESSED:
                # If the key already exists in the state and was not processed,
                # nothing should be done
                pass
            elif post_processing_status == IncrementalStateStatus.PERMANENTLY_EXCLUDED:
                # The source authoritatively answered "this key does not exist".
                # A key that once SUCCEEDED and is now absent was deleted at the
                # source — that is the existing DELETED semantic;
                # PERMANENTLY_EXCLUDED is reserved for keys that never existed.
                if state.status == IncrementalStateStatus.SUCCEEDED:
                    state.status = IncrementalStateStatus.DELETED
                    state.source_deleted_at = processing_state.processing_completed_at
                else:
                    state.status = IncrementalStateStatus.PERMANENTLY_EXCLUDED
                state.last_processed_at = processing_state.processing_completed_at
                state.last_process_status = post_processing_status
                state.last_process_error_message = None
                state.parameters = processing_state.parameters
            elif post_processing_status == IncrementalStateStatus.FAILED:
                # If the current process failed but the process succeeded once,
                # the status is kept on succeeded
                state.status = (
                    state.status
                    if state.status == IncrementalStateStatus.SUCCEEDED
                    else post_processing_status
                )
                state.last_processed_at = processing_state.processing_completed_at
                state.last_process_status = post_processing_status
                state.last_process_error_message = (
                    processing_state.process_error_message
                )
                state.parameters = processing_state.parameters
            elif post_processing_status == IncrementalStateStatus.SUCCEEDED:
                state.status = post_processing_status
                state.last_successfully_processed_at = (
                    processing_state.processing_completed_at
                )
                state.last_processed_at = processing_state.processing_completed_at
                state.last_process_status = post_processing_status
                state.last_process_error_message = None
                state.parameters = processing_state.parameters
        else:
            self.post_processing_state.add_single_key_flow_state(
                ByKeySingleKeyState(
                    name=key_name,
                    status=post_processing_status,
                    last_successfully_processed_at=(
                        processing_state.processing_completed_at
                        if post_processing_status == IncrementalStateStatus.SUCCEEDED
                        else None
                    ),
                    last_processed_at=processing_state.processing_completed_at,
                    last_process_status=post_processing_status,
                    last_process_error_message=(
                        processing_state.process_error_message
                        if post_processing_status == IncrementalStateStatus.FAILED
                        else None
                    ),
                    first_processed_at=processing_state.processing_completed_at,
                    source_deleted_at=None,
                    parameters=processing_state.parameters,
                )
            )

    def _update_post_processing_from_processing_state(self) -> None:
        assert self.post_processing_state is not None
        for key_name in self.processing_state.keys:
            self._update_post_processing_from_processing_state_for_single_key(key_name)

    def create_post_processing_state(self) -> ByKeyState:
        # --- Step 1 / Reuse the latest incremental state as the post-processing
        # state, updating it in place. The key state accumulates one entry per
        # key ever seen and can hold hundreds of thousands of entries; deep
        # copying it here doubled the in-memory footprint at the most
        # memory-intensive point of the run and could OOM the worker. No
        # consumer reads ``latest_incremental_state`` after this point, so
        # mutating it in place is safe and keeps peak memory O(existing keys)
        # instead of O(2 * existing keys).
        self.post_processing_state = cast(ByKeyState, self.latest_incremental_state)
        # --- Step 2 / Update the post-processing state with the processing state
        if self.strategy in [
            FlowLoadingStrategies.FULL,
            FlowLoadingStrategies.DELTA,
            FlowLoadingStrategies.BACKFILL_DELTA,
            FlowLoadingStrategies.BACKFILL,
        ]:
            self._update_post_processing_from_processing_state()

        return self.post_processing_state

    def create_partial_post_processing_state(self, identifier: Any) -> None:
        """Create or update the post-processing state for a single key."""
        # --- Step 1 / Lazily bind the post-processing state to the latest
        # incremental state, updating it in place (see ``create_post_processing_state``
        # for why this is not deep copied).
        if self.post_processing_state is None:
            self.post_processing_state = cast(ByKeyState, self.latest_incremental_state)

        # --- Step 2 / Update the post-processing state for this key
        self._update_post_processing_from_processing_state_for_single_key(identifier)
