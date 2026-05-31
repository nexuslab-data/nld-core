import datetime
from typing import Any

from pydantic import Field

from nld.flow.incremental.models import (
    FlowPlannedProcessingState,
    FlowProcessingState,
    FlowSourceState,
    FlowState,
    IncrementalProcessingStatus,
    IncrementalStateStatus,
)
from nld.pydantic import NldBaseModel
from nld.utils.datetime_util import get_current_datetime


class ByKeySingleKeyState(NldBaseModel):
    name: str
    status: str = IncrementalStateStatus.NOT_PROCESSED
    last_successfully_processed_at: datetime.datetime | None = None
    last_processed_at: datetime.datetime | None = None
    last_process_status: str = IncrementalStateStatus.NOT_PROCESSED
    last_process_error_message: str | None = None
    first_processed_at: datetime.datetime | None = None
    source_deleted_at: datetime.datetime | None = None
    parameters: dict[str, Any] | None = None

    # Processing Status methods
    def set_to_not_processed(self) -> None:
        self.status = IncrementalStateStatus.NOT_PROCESSED

    def set_to_deleted(self) -> None:
        self.status = IncrementalStateStatus.DELETED

    def set_to_succeeded(self) -> None:
        self.status = IncrementalStateStatus.SUCCEEDED

    def set_to_failed(self) -> None:
        self.status = IncrementalStateStatus.FAILED

    def not_processed(self) -> bool:
        return self.status == IncrementalStateStatus.NOT_PROCESSED

    def deleted(self) -> bool:
        return self.status == IncrementalStateStatus.DELETED

    def succeeded(self) -> bool:
        return self.status == IncrementalStateStatus.SUCCEEDED

    def failed(self) -> bool:
        return self.status == IncrementalStateStatus.FAILED


class ByKeyState(FlowState):
    keys: dict[str, ByKeySingleKeyState] = Field(default_factory=dict)

    def has_key(self, key: str) -> bool:
        return key in self.keys.keys()

    def add_single_key_flow_state(self, single_key_state: ByKeySingleKeyState) -> None:
        self.keys.update({single_key_state.name: single_key_state})

    def get_succeeded_keys(self) -> dict[str, ByKeySingleKeyState]:
        return {key: state for key, state in self.keys.items() if state.succeeded()}

    def get_not_processed_keys(self) -> list[str]:
        return [key for key, state in self.keys.items() if state.not_processed()]

    def get_failed_keys(self) -> list[str]:
        return [key for key, state in self.keys.items() if state.failed()]

    def get_not_processed_states(self) -> list[ByKeySingleKeyState]:
        return [state for state in self.keys.values() if state.not_processed()]

    def get_failed_states(self) -> list[ByKeySingleKeyState]:
        return [state for state in self.keys.values() if state.failed()]


# Flow Source State - By Key incremental - Standard source state


class ByKeySingleKeySourceState(NldBaseModel):
    name: str
    last_updated_at: datetime.datetime | None = None
    parameters: dict[str, Any] | None = None


class ByKeySourceState(FlowSourceState):
    keys: dict[str, ByKeySingleKeySourceState]


# Flow Processing State - By Key incremental - Standard processing state


class ByKeySingleKeyProcessingState(NldBaseModel):
    name: str
    processing_status: str = IncrementalProcessingStatus.TO_BE_PROCESSED
    process_error_message: str | None = None
    processing_completed_at: datetime.datetime | None = None
    parameters: dict[str, Any] | None = None

    # Processing Status methods
    def set_to_be_processed(self) -> None:
        self.processing_status = IncrementalProcessingStatus.TO_BE_PROCESSED

    def set_to_excluded(self) -> None:
        self.processing_status = IncrementalProcessingStatus.EXCLUDED

    def set_to_succeeded(self) -> None:
        self.processing_status = IncrementalProcessingStatus.SUCCEEDED
        self.processing_completed_at = get_current_datetime()

    def set_to_failed(self, error_message: str | None = None) -> None:
        self.processing_status = IncrementalProcessingStatus.FAILED
        self.process_error_message = error_message
        self.processing_completed_at = get_current_datetime()

    def to_be_processed(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.TO_BE_PROCESSED

    def excluded(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.EXCLUDED

    def succeeded(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.SUCCEEDED

    def failed(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.FAILED


class ByKeyProcessingState(FlowProcessingState):
    keys: dict[str, ByKeySingleKeyProcessingState]

    def get_display_log(self) -> str:
        """Return a human-readable summary of the processing state."""
        count = len(self.get_keys_to_process())
        return f"Strategy: {self.strategy} | Keys to process: {count}"

    def has_key(self, key: str) -> bool:
        return key in self.keys.keys()

    def add_single_key_flow_processing_state(
        self, single_key_processing_state: ByKeySingleKeyProcessingState
    ) -> None:
        self.keys.update(
            {single_key_processing_state.name: single_key_processing_state}
        )

    def get_keys_to_process(self) -> list[ByKeySingleKeyProcessingState]:
        return [key for key in self.keys.values() if key.to_be_processed()]

    def get_failed(self) -> dict[str, ByKeySingleKeyProcessingState]:
        return {key: value for key, value in self.keys.items() if value.failed()}

    def set_all_to_be_processed(self) -> None:
        for key in self.keys.values():
            key.set_to_be_processed()


class ByKeyPlannedProcessingState(FlowPlannedProcessingState[ByKeyProcessingState]):
    """A PLANNED plan carrying a by_key processing-state payload."""
