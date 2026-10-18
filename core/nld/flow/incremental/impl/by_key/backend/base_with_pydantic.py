import abc
import datetime
from collections.abc import Collection, Mapping
from typing import Any

from nld.connector.base.connector import DataConnector
from nld.flow.incremental.base.manager import (
    IncrementalBackendStateManager,
)
from nld.flow.incremental.impl.by_key.state import (
    ByKeyPlannedProcessingDetailedState,
    ByKeyPlannedProcessingState,
    ByKeyProcessingState,
    ByKeySourceState,
    ByKeyState,
)
from nld.flow.incremental.models import IncrementalStateStatus


class ByKeyStateBackendManager[DATA_CONNECTOR: DataConnector[Any]](
    IncrementalBackendStateManager[
        DATA_CONNECTOR,
        ByKeyState,
        ByKeySourceState,
        ByKeyProcessingState,
        ByKeyPlannedProcessingState,
        ByKeyPlannedProcessingDetailedState,
    ],
    abc.ABC,
):
    """Base class of the by_key state backend managers.

    A backend that stores the key state in a queryable file can opt in to the
    key state merge with ``supports_key_state_merge``. A run then never loads
    the whole key state: it reads the terminal key names, the keys updated in
    the source and the state of the keys it processed, then merges those
    keys back into the stored state.
    """

    def supports_key_state_merge(self) -> bool:
        """Whether the backend merges updated keys into the stored key state."""
        return False

    def prepare_current_state(self) -> None:
        """Make the current key state queryable without loading it in memory."""
        raise NotImplementedError(
            f"'prepare_current_state' is not implemented for {type(self).__name__}"
        )

    def read_terminal_key_names(self) -> set[str]:
        """Return the names of the keys delta strategies must not re-attempt."""
        raise NotImplementedError(
            f"'read_terminal_key_names' is not implemented for {type(self).__name__}"
        )

    def read_source_updated_key_names(
        self,
        source_last_updated_at: Mapping[str, datetime.datetime],
    ) -> set[str]:
        """Return the SUCCEEDED keys the source updated since their last success.

        A key qualifies when its source timestamp is later than the one stored
        by its last success, or than ``last_successfully_processed_at`` when
        none was stored, as in ``ByKeySingleKeyState.updated_in_source``.

        Args:
            source_last_updated_at: Source update timestamp of each source key.
        """
        raise NotImplementedError(
            "'read_source_updated_key_names' is not implemented for "
            f"{type(self).__name__}"
        )

    def read_current_key_states(self, names: Collection[str]) -> ByKeyState:
        """Return the stored state of the given keys only.

        Keys absent from the stored state are absent from the result.

        Args:
            names: Names of the keys to read.
        """
        raise NotImplementedError(
            f"'read_current_key_states' is not implemented for {type(self).__name__}"
        )

    def merge_into_current_state(self, key_states: ByKeyState) -> None:
        """Replace or add the given keys in the stored key state.

        Every stored key absent from ``key_states`` is kept unchanged.

        Args:
            key_states: The updated state of the keys a run processed.
        """
        raise NotImplementedError(
            f"'merge_into_current_state' is not implemented for {type(self).__name__}"
        )

    def set_keys_to_permanently_excluded(
        self,
        names: Collection[str],
    ) -> dict[str, str | None]:
        """Set the given keys to PERMANENTLY_EXCLUDED in the stored key state.

        Every other stored key is kept unchanged. A backend merging the key
        state reads and merges back only the given keys; the other backends
        read the whole state and write it back. Nothing is written when
        every key is already excluded.

        Args:
            names: Names of the keys to exclude.

        Returns:
            The previous status of each key, None for a key the state did
            not hold.
        """
        merges_key_state = self.supports_key_state_merge()
        if merges_key_state:
            self.prepare_current_state()
            key_states = self.read_current_key_states(names=names)
        else:
            key_states = self.read_current_state()
        previous_statuses = key_states.set_keys_to_permanently_excluded(names=names)
        if all(
            status == IncrementalStateStatus.PERMANENTLY_EXCLUDED
            for status in previous_statuses.values()
        ):
            return previous_statuses
        if merges_key_state:
            self.merge_into_current_state(key_states=key_states)
        else:
            self.write_post_processing_state(
                post_processing_flow_state=key_states,
            )
        return previous_statuses
