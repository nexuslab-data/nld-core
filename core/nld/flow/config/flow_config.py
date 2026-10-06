from typing import Any

from pydantic import Field as PydanticField
from pydantic import field_validator

from nld.flow.alerting.models import FlowAlertTransportManifest
from nld.flow.config.state_backend_connector import StateBackendConnectorConfigWrapper
from nld.flow.incremental.models import (
    FLOW_INCREMENTAL_TYPE_LITERAL,
    FlowIncrementalTypeManifest,
)
from nld.flow.quality.models import DataQualityRuleManifest
from nld.flow.utils import FLOW_LOADING_STRATEGY_LITERAL
from nld.pydantic import NamespaceMappingConfig
from nld.pydantic.base_model import NldBaseModel


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


class FlowProjectConfig(NldBaseModel):
    """General (non-namespaced) flow configuration of a project.

    Loaded from the ``flow`` block of ``nld_project.yml``. It gathers the
    flow-domain extension points a project registers at load time: the task
    types its flows may declare, the incremental types they may use, the
    data quality rules their quality checks may reference, and the alert
    transports its alerting declarations may name.

    Namespace-scoped flow settings live under the ``namespaces`` block instead
    (see ``FlowNamespaceConfig``).

    Example YAML:
        flow:
          additional_flow_task_types:
            custom: my_project.flows.custom_task.CustomFlowTask
          additional_quality_rules:
            - name: column_percentage_range
              rule_class: my_project.quality.ColumnPercentageRangeRule
          additional_alert_transports:
            - name: pagerduty
              transport_class: my_platform.alerting.PagerDutyAlertTransport
    """

    additional_flow_task_types: dict[str, str] = PydanticField(
        default_factory=dict,
    )
    additional_incremental_types: list[FlowIncrementalTypeManifest] = PydanticField(
        default_factory=list,
    )
    additional_quality_rules: list[DataQualityRuleManifest] = PydanticField(
        default_factory=list,
    )
    additional_alert_transports: list[FlowAlertTransportManifest] = PydanticField(
        default_factory=list,
    )


class FlowNamespaceMapping(NldBaseModel):
    """Maps a namespace to default flow configuration."""

    default_state_backend_connector: StateBackendConnectorConfigWrapper | None = None

    @field_validator("default_state_backend_connector", mode="before")
    @classmethod
    def coerce_string_state_backend(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"primary": {"connector": value}}
        return value


class FlowNamespaceConfig(NamespaceMappingConfig[FlowNamespaceMapping]):
    """Namespace-scoped flow settings of a project.

    Declared under the ``namespaces`` block of ``nld_project.yml``, one ``flow``
    entry per namespace. See ``NamespaceMappingConfig`` for how a namespace
    resolves to its nearest mapping.

    Example YAML:
        namespaces:
          source.raw:
            flow:
              default_state_backend_connector: pg_backend
    """

    def get_mapping(self, namespace: str) -> FlowNamespaceMapping | None:
        """Return the mapping for a namespace, or None when none applies."""
        return self.find_mapping(namespace=namespace)

    def get_default_state_backend_connector(
        self,
        namespace: str,
    ) -> StateBackendConnectorConfigWrapper | None:
        """Return the default state backend connector for the given namespace."""
        mapping = self.find_mapping(namespace=namespace)
        if mapping is None:
            return None
        return mapping.default_state_backend_connector
