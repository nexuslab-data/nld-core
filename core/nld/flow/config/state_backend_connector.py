from typing import Any

from pydantic import field_validator

from nld.flow.config.connection_config import ConnectorConfig, coerce_connector_config
from nld.pydantic import NldBaseModel


class StateBackendConnectorConfigWrapper(NldBaseModel):
    """Pair of per-side state-backend configs (primary + optional secondary).

    The primary backend is authoritative: all reads and cross-run queries
    of execution and incremental state go to it. The secondary backend,
    when set, receives a dual-write copy of the current run's execution
    and incremental state so that per-run artifacts can live next to the
    produced data (e.g. on an S3 target) without making the target the
    source of truth.

    This class wraps two ``ConnectorConfig`` per-side configs. The runtime
    wrapper that pairs configs with live ``DataConnector`` instances is
    ``StateBackendConnectorWrapper``.
    """

    primary: ConnectorConfig
    secondary: ConnectorConfig | None = None

    @field_validator("primary", "secondary", mode="before")
    @classmethod
    def coerce_string_side(cls, value: Any) -> Any:
        return coerce_connector_config(value)


def _merge_state_backend_connector_config_for_one_side(
    flow_state_backend_connector_config: ConnectorConfig | None,
    project_default_state_backend_connector_config: ConnectorConfig | None,
) -> ConnectorConfig | None:
    if flow_state_backend_connector_config is None:
        return project_default_state_backend_connector_config
    if project_default_state_backend_connector_config is None:
        return flow_state_backend_connector_config
    return ConnectorConfig(
        connector=flow_state_backend_connector_config.connector,
        params={
            **project_default_state_backend_connector_config.params,
            **flow_state_backend_connector_config.params,
        },
        profile_name=(
            flow_state_backend_connector_config.profile_name
            if flow_state_backend_connector_config.profile_name is not None
            else project_default_state_backend_connector_config.profile_name
        ),
    )


def merge_state_backend_connector_config_wrappers(
    flow_state_backend_connector_config_wrapper: (
        StateBackendConnectorConfigWrapper | None
    ),
    project_default_state_backend_connector_config_wrapper: (
        StateBackendConnectorConfigWrapper | None
    ),
) -> StateBackendConnectorConfigWrapper | None:
    """Merge a flow-level state backend connector with a project default.

    The flow value takes precedence. When both levels declare the same
    side, the flow's ``connector`` wins and ``params`` are merged
    field-by-field with flow params overriding project params (so a
    project-wide ``file_format`` default still applies unless the flow
    overrides it).
    """
    if flow_state_backend_connector_config_wrapper is None:
        return project_default_state_backend_connector_config_wrapper
    if project_default_state_backend_connector_config_wrapper is None:
        return flow_state_backend_connector_config_wrapper
    primary = _merge_state_backend_connector_config_for_one_side(
        flow_state_backend_connector_config=(
            flow_state_backend_connector_config_wrapper.primary
        ),
        project_default_state_backend_connector_config=(
            project_default_state_backend_connector_config_wrapper.primary
        ),
    )
    secondary = _merge_state_backend_connector_config_for_one_side(
        flow_state_backend_connector_config=(
            flow_state_backend_connector_config_wrapper.secondary
        ),
        project_default_state_backend_connector_config=(
            project_default_state_backend_connector_config_wrapper.secondary
        ),
    )
    assert primary is not None
    return StateBackendConnectorConfigWrapper(
        primary=primary,
        secondary=secondary,
    )
