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
    BY_KEY_SOURCE_FULL_FLOW_INCREMENTAL_LOGIC,
    ByKeySourceFullFlowIncrementalParams,
)
from .state import (
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
        ByKeySourceFullFlowIncrementalParams,
    ]
):
    flow_incremental_logic = BY_KEY_SOURCE_FULL_FLOW_INCREMENTAL_LOGIC

    def __init__(
        self,
        incremental_parameters: ByKeySourceFullFlowIncrementalParams,
        incremental_state_backend_manager: IncrementalBackendStateManager[
            DataConnector[Any],
            ByKeyState,
            ByKeySourceState,
            ByKeyProcessingState,
            ByKeyPlannedProcessingState,
        ]
        | None = None,
        secondary_incremental_state_backend_manager: IncrementalBackendStateManager[
            DataConnector[Any],
            ByKeyState,
            ByKeySourceState,
            ByKeyProcessingState,
            ByKeyPlannedProcessingState,
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
        - Key latest incremental should not have SUCCEEDED status
        - Key should be in source state (in the list of keys to be retrieved)
        """
        assert self.source_state is not None
        self.incremental_parameters: ByKeySourceFullFlowIncrementalParams
        if self.strategy in [FlowLoadingStrategies.DELTA]:
            assert self.latest_incremental_state is not None
            for key, flow_source_state in self.source_state.keys.items():
                if key not in self.latest_incremental_state.get_succeeded_keys():
                    flow_processing_state = ByKeySingleKeyProcessingState(
                        name=key,
                        parameters=flow_source_state.parameters,
                        processing_status=IncrementalProcessingStatus.TO_BE_PROCESSED,
                    )
                    self.processing_state.keys.update({key: flow_processing_state})
        elif self.strategy in [FlowLoadingStrategies.BACKFILL_DELTA]:
            assert self.latest_incremental_state is not None
            succeeded_keys = self.latest_incremental_state.get_succeeded_keys()
            self._apply_backfill_filtering(exclude_succeeded_keys=succeeded_keys)
        elif self.strategy in [FlowLoadingStrategies.BACKFILL]:
            self._apply_backfill_filtering(exclude_succeeded_keys=None)
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
        exclude_succeeded_keys: dict[str, Any] | None,
    ) -> None:
        """Apply backfill key filtering with optional delta exclusion.

        Args:
            exclude_succeeded_keys: If provided, keys in this dict are excluded
                from processing (used by BACKFILL_DELTA to skip
                already-succeeded keys).
        """
        assert self.source_state is not None

        if self.incremental_parameters.limit is not None:
            for key, flow_source_state in self.source_state.keys.items():
                should_exclude = (
                    exclude_succeeded_keys is not None and key in exclude_succeeded_keys
                )
                flow_processing_state = ByKeySingleKeyProcessingState(
                    name=key,
                    parameters=flow_source_state.parameters,
                    processing_status=IncrementalProcessingStatus.EXCLUDED,
                )
                self.processing_state.keys.update({key: flow_processing_state})
                if should_exclude:
                    continue
            if self.incremental_parameters.limit > 0:
                count = 0
                for processing_state in self.processing_state.keys.values():
                    if (
                        processing_state.excluded()
                        and count < self.incremental_parameters.limit
                    ):
                        if (
                            exclude_succeeded_keys is None
                            or processing_state.name not in exclude_succeeded_keys
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
                    should_exclude = (
                        exclude_succeeded_keys is not None
                        and key in exclude_succeeded_keys
                    )
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
        else:
            post_processing_status = IncrementalStateStatus.NOT_PROCESSED

        # --- Step 2 / Update post-processing state (update or add)
        if self.post_processing_state.has_key(key_name):
            state = self.post_processing_state.keys[key_name]
            if post_processing_status == IncrementalStateStatus.NOT_PROCESSED:
                # If the key already exists in the state and was not processed,
                # nothing should be done
                pass
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
        # --- Step 1 / Initialize post-processing state with existing state
        self.post_processing_state = ByKeyState.deep_copy(
            cast(ByKeyState, self.latest_incremental_state)
        )
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
        # --- Step 1 / Lazily initialize post-processing state
        if self.post_processing_state is None:
            self.post_processing_state = ByKeyState.deep_copy(
                cast(ByKeyState, self.latest_incremental_state)
            )

        # --- Step 2 / Update the post-processing state for this key
        self._update_post_processing_from_processing_state_for_single_key(identifier)
