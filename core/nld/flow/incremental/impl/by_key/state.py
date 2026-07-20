import datetime
from typing import Any

from pydantic import Field

from nld.flow.incremental.models import (
    FlowPlannedProcessingDetailledState,
    FlowPlannedProcessingState,
    FlowProcessingState,
    FlowSourceState,
    FlowState,
    IncrementalProcessingStatus,
    IncrementalStateStatus,
)
from nld.pydantic import NldBaseModel
from nld.utils.datetime_util import get_current_datetime
from nld.utils.user_display import (
    format_datetime_for_display,
    format_key_value_lines,
)

KEYS_SAMPLE_SIZE = 10


def render_by_key_entries(
    entries: list[tuple[str, str, datetime.datetime | None]],
) -> str:
    """Render aggregate counts plus to-be-processed and last-retrieved samples.

    ``entries`` is an ordered ``(name, status, retrieved_at)`` list so the
    to-be-processed sample keeps source order and the last-retrieved sample
    can order by timestamp. Shared by the processing and current views so
    both look identical while owning their own field mapping.
    """
    counts: dict[str, int] = {}
    to_be_processed: list[str] = []
    for name, status, _ in entries:
        label = status or "N/A"
        counts[label] = counts.get(label, 0) + 1
        if label == IncrementalProcessingStatus.TO_BE_PROCESSED:
            to_be_processed.append(name)

    pairs: list[tuple[str, str]] = [("Keys total", str(len(entries)))]
    for status, count in sorted(counts.items()):
        pairs.append((status, str(count)))
    lines = format_key_value_lines(pairs=pairs)

    sample = to_be_processed[:KEYS_SAMPLE_SIZE]
    if sample:
        header = (
            f"  Sample of to be processed ({len(sample)} of {len(to_be_processed)}):"
            if len(to_be_processed) > len(sample)
            else f"  Sample of to be processed ({len(sample)}):"
        )
        lines.append(header)
        lines.extend(f"    - {name}" for name in sample)

    retrieved = [(name, timestamp) for name, _, timestamp in entries if timestamp]
    if retrieved:
        retrieved.sort(key=lambda item: item[1], reverse=True)
        retrieved_sample = retrieved[:KEYS_SAMPLE_SIZE]
        header = (
            f"  Sample of last retrieved ({len(retrieved_sample)} of {len(retrieved)}):"
            if len(retrieved) > len(retrieved_sample)
            else f"  Sample of last retrieved ({len(retrieved_sample)}):"
        )
        lines.append(header)
        for name, timestamp in retrieved_sample:
            display = format_datetime_for_display(value=timestamp)
            lines.append(f"    - {name} ({display})")
    return "\n".join(lines)


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

    def set_to_permanently_excluded(self) -> None:
        self.status = IncrementalStateStatus.PERMANENTLY_EXCLUDED

    def not_processed(self) -> bool:
        return self.status == IncrementalStateStatus.NOT_PROCESSED

    def deleted(self) -> bool:
        return self.status == IncrementalStateStatus.DELETED

    def succeeded(self) -> bool:
        return self.status == IncrementalStateStatus.SUCCEEDED

    def failed(self) -> bool:
        return self.status == IncrementalStateStatus.FAILED

    def permanently_excluded(self) -> bool:
        return self.status == IncrementalStateStatus.PERMANENTLY_EXCLUDED

    def terminal(self) -> bool:
        """True when the key must not be re-attempted by delta strategies."""
        return self.succeeded() or self.permanently_excluded()


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

    def get_permanently_excluded_keys(self) -> dict[str, ByKeySingleKeyState]:
        return {
            key: state
            for key, state in self.keys.items()
            if state.permanently_excluded()
        }

    def get_terminal_keys(self) -> dict[str, ByKeySingleKeyState]:
        """Keys delta strategies must never re-attempt.

        SUCCEEDED and PERMANENTLY_EXCLUDED alike.
        """
        return {key: state for key, state in self.keys.items() if state.terminal()}

    def render_state_text(self) -> str:
        """Render per-key counts and a sample of the last retrieved keys."""
        entries = [
            (name, key.status, key.last_successfully_processed_at)
            for name, key in self.keys.items()
        ]
        return render_by_key_entries(entries=entries)


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

    def set_to_permanently_excluded(self) -> None:
        self.processing_status = IncrementalProcessingStatus.PERMANENTLY_EXCLUDED
        self.processing_completed_at = get_current_datetime()

    def to_be_processed(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.TO_BE_PROCESSED

    def excluded(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.EXCLUDED

    def succeeded(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.SUCCEEDED

    def failed(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.FAILED

    def permanently_excluded(self) -> bool:
        return (
            self.processing_status == IncrementalProcessingStatus.PERMANENTLY_EXCLUDED
        )


class ByKeyProcessingState(FlowProcessingState):
    keys: dict[str, ByKeySingleKeyProcessingState]

    def get_display_log(self) -> str:
        """Return a human-readable summary of the processing state."""
        count = len(self.get_keys_to_process())
        return f"Strategy: {self.strategy} | Keys to process: {count}"

    def render_state_text(self) -> str:
        """Render per-key counts and a sample of the keys just processed."""
        entries = [
            (name, key.processing_status, key.processing_completed_at)
            for name, key in self.keys.items()
        ]
        return render_by_key_entries(entries=entries)

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


class ByKeySingleKeyPlannedProcessingDetailledState(NldBaseModel):
    name: str
    planned_processing_status: str = IncrementalProcessingStatus.TO_BE_PROCESSED
    parameters: dict[str, Any] | None = None


class ByKeyPlannedProcessingDetailledState(
    FlowPlannedProcessingDetailledState[ByKeyProcessingState],
):
    """Plan-time detail for a by_key PLANNED plan."""

    strategy: str
    keys: dict[str, ByKeySingleKeyPlannedProcessingDetailledState]

    def to_processing_state(self, flow_uid: str) -> ByKeyProcessingState:
        return ByKeyProcessingState(
            flow_uid=flow_uid,
            strategy=self.strategy,
            keys={
                name: ByKeySingleKeyProcessingState(
                    name=key.name,
                    processing_status=key.planned_processing_status,
                    parameters=key.parameters,
                )
                for name, key in self.keys.items()
            },
        )

    @classmethod
    def from_processing_state(
        cls,
        plan_state_uid: str,
        processing_state: ByKeyProcessingState,
    ) -> "ByKeyPlannedProcessingDetailledState":
        return cls(
            plan_state_uid=plan_state_uid,
            strategy=processing_state.strategy,
            keys={
                name: ByKeySingleKeyPlannedProcessingDetailledState(
                    name=key.name,
                    planned_processing_status=key.processing_status,
                    parameters=key.parameters,
                )
                for name, key in processing_state.keys.items()
            },
        )


class ByKeyPlannedProcessingState(
    FlowPlannedProcessingState[ByKeyPlannedProcessingDetailledState],
):
    """A PLANNED plan carrying a by_key planned-detail payload."""
