from nld.pydantic import NldBaseModel


class IncrementalConfig(NldBaseModel):
    """Configuration for incremental processing on a data flow."""

    strategy: str
    persist_initial_processing_state: bool = True
    immediate_step_persistence: bool = True
