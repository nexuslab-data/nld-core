import abc
import datetime

from nld.pydantic import NldBaseModel


class FlowState(NldBaseModel):
    pass


class FlowProcessingState(NldBaseModel):
    flow_uid: str
    strategy: str

    @abc.abstractmethod
    def get_display_log(self) -> str:
        """Return a human-readable summary of the processing state."""
        raise NotImplementedError(
            "The method 'get_display_log' should be implemented in sub class."
        )

    def get_pull_timestamps(
        self,
    ) -> tuple[datetime.datetime | None, datetime.datetime | None]:
        """Return (pull_from, pull_to) timestamps if applicable.

        Subclasses with timestamp-based incremental strategies
        should override this to return their actual timestamps.
        """
        return None, None


class FlowSourceState(NldBaseModel):
    pass
