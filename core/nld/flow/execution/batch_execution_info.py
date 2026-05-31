from pydantic import Field

from nld.flow.execution.execution_info import FlowExecutionInfo
from nld.pydantic import NldBaseModel


class FlowExecutionInfoWrapper(NldBaseModel):
    """Wraps the results of executing one or more flows."""

    namespace: str
    execution_order: list[str]
    flow_results: list[FlowExecutionInfo] = Field(default_factory=list)
    failed_flows: dict[str, str] = Field(default_factory=dict)
    skipped_flows: dict[str, str] = Field(default_factory=dict)
    skipped_views: list[str] = Field(default_factory=list)

    @property
    def total_flows(self) -> int:
        return len(self.execution_order)

    @property
    def succeeded_flows(self) -> list[str]:
        return [
            _build_display_id(
                flow_namespace=result.flow_namespace,
                flow_name=result.flow_name,
            )
            for result in self.flow_results
        ]


def _build_display_id(
    flow_namespace: str,
    flow_name: str,
) -> str:
    """Build a display ID from namespace and flow name."""
    if flow_namespace and flow_namespace != ".":
        return f"{flow_namespace}.{flow_name}"
    return flow_name
