from typing import Any

from pydantic import Field as PydanticField
from pydantic import field_validator

from nld.flow.incremental.models import FLOW_INCREMENTAL_TYPE_LITERAL
from nld.flow.state.config import StateBackendConnectorConfigWrapper
from nld.flow.utils import FLOW_LOADING_STRATEGY_LITERAL
from nld.pydantic.base_model import NldBaseModel
from nld.pydantic.namespace import NldNamespace


class FlowConfig(NldBaseModel):
    flow_namespace: str
    flow_name: str
    flow_instance_name: str
    target_schema: str
    target_table: str
    default_data_loading_strategy: FLOW_LOADING_STRATEGY_LITERAL
    historical_refresh_authorized: bool
    incremental_type: FLOW_INCREMENTAL_TYPE_LITERAL
    pull_field_name: str | None = None
    pull_field_format: str | None = None
    target_field_name_for_previous_layer_last_update_tst: str | None = None
    target_field_name_for_source_extraction_tst: str | None = None
    target_field_name_for_source_last_update_tst: str | None = None
    delta_period_reference_type: str | None = None
    delta_period_reference: str | None = None
    delta_period_range_from_type: str | None = None
    delta_period_range_from: str | None = None
    delta_period_range_to_type: str | None = None
    delta_period_range_to: str | None = None


class FlowProjectMapping(NldBaseModel):
    """Maps a namespace to default flow configuration."""

    default_state_backend_connector: StateBackendConnectorConfigWrapper | None = None

    @field_validator("default_state_backend_connector", mode="before")
    @classmethod
    def coerce_string_state_backend(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"primary": {"connector": value}}
        return value


class FlowProjectConfig(NldBaseModel):
    """Configuration mapping namespaces to default flow settings.

    When a namespace is not explicitly configured, the lookup walks up the
    hierarchy until a match is found. A root mapping (".") acts as a
    fallback for all namespaces.

    Loaded from config/flow.yaml in the project root.

    Example YAML:
        additional_flow_task_types:
          custom: my_project.flows.custom_task.CustomFlowTask
        mappings:
          source.raw:
            default_state_backend_connector: pg_backend
    """

    additional_flow_task_types: dict[str, str] = PydanticField(
        default_factory=dict,
    )
    mappings: dict[str, FlowProjectMapping]

    def get_mapping(self, namespace: str) -> FlowProjectMapping | None:
        """Return the mapping for the given namespace, or None.

        Walks up the namespace hierarchy to find the closest matching
        mapping.
        """
        nld_namespace = NldNamespace(namespace)
        for ancestor in reversed(nld_namespace.hierarchy):
            if str(ancestor) in self.mappings:
                return self.mappings[str(ancestor)]
        return None

    def get_namespaces(self) -> list[str]:
        """Return all configured namespace keys."""
        return list(self.mappings.keys())

    def get_default_state_backend_connector(
        self,
        namespace: str,
    ) -> StateBackendConnectorConfigWrapper | None:
        """Return the default state backend connector for the given namespace."""
        mapping = self.get_mapping(namespace=namespace)
        if mapping is None:
            return None
        return mapping.default_state_backend_connector
