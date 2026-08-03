from pydantic import field_validator

from nld.flow.incremental.models.referential import SourceAvailability
from nld.pydantic import NldBaseModel


class IncrementalConfig(NldBaseModel):
    """Configuration for incremental processing on a data flow."""

    type: str
    persist_initial_processing_state: bool = True
    immediate_step_persistence: bool = True
    # Per-flow override of the definition-level source availability;
    # None keeps the incremental definition default.
    source_availability: str | None = None

    @field_validator("source_availability")
    @classmethod
    def validate_source_availability(cls, value: str | None) -> str | None:
        """Reject values outside the SourceAvailability vocabulary."""
        if value is not None:
            SourceAvailability(value)
        return value
