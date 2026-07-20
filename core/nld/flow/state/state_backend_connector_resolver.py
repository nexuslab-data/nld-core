from typing import TYPE_CHECKING, Any, Literal

from pydantic import ConfigDict

from nld.connector.base.connector import DataConnector
from nld.flow.config import (
    ConnectorConfig,
    StateBackendConnectorConfigWrapper,
    merge_state_backend_connector_config_wrappers,
)
from nld.pydantic import NldBaseModel
from nld.task.context import NldExecutionContext

# NamespacedDataFlowDefinition is referenced only as a parameter type;
# importing nld.flow.definition at runtime would risk a circular import,
# so it is kept under TYPE_CHECKING.
if TYPE_CHECKING:
    from nld.flow.definition.flow_definition import NamespacedDataFlowDefinition


class StateBackendConnector(NldBaseModel):
    """Live state-backend side: a ``DataConnector`` paired with its config.

    Used to pass a single primary or secondary side to the execution
    backend factory in one argument instead of carrying the connector
    and the per-side ``params`` dict separately.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data_connector: DataConnector[Any]
    config: ConnectorConfig


class StateBackendConnectorWrapper(NldBaseModel):
    """Pair of live state-backend sides (primary + optional secondary).

    Mirrors the shape of ``StateBackendConnectorConfigWrapper`` but each
    side carries the live ``DataConnector`` next to its config, so the
    wrapper can be passed end-to-end from the executor down to the state
    factories without re-resolving anything.
    """

    primary: StateBackendConnector
    secondary: StateBackendConnector | None = None


def build_effective_state_backend_connector_config_wrapper(
    namespaced_data_flow_definition: "NamespacedDataFlowDefinition",
    execution_context: NldExecutionContext,
) -> StateBackendConnectorConfigWrapper | None:
    """Merge the flow-level state-backend declaration with the project default.

    Pure: does not touch the connector registry. Used by code paths that
    already have the live connectors injected (e.g.
    ``DataFlowTask.init_state_manager``).
    """
    data_flow_definition = namespaced_data_flow_definition.model
    flow_namespace = str(namespaced_data_flow_definition.namespace)
    flow_state_backend_connector_config_wrapper = (
        data_flow_definition.state_backend_connector
    )
    flow_config = getattr(execution_context.project, "flow_config", None)
    project_default_state_backend_connector_config_wrapper = (
        flow_config.get_default_state_backend_connector(
            namespace=flow_namespace,
        )
        if flow_config is not None
        else None
    )
    return merge_state_backend_connector_config_wrappers(
        flow_state_backend_connector_config_wrapper=(
            flow_state_backend_connector_config_wrapper
        ),
        project_default_state_backend_connector_config_wrapper=(
            project_default_state_backend_connector_config_wrapper
        ),
    )


def build_state_backend_connector_wrapper(
    namespaced_data_flow_definition: "NamespacedDataFlowDefinition",
    execution_context: NldExecutionContext,
    open_connection: bool,
    override_profile_name: str | None = None,
) -> StateBackendConnectorWrapper | None:
    """Resolve the effective state backend AND the live primary/secondary connectors.

    Returns ``None`` when neither the flow nor the project declares a
    state backend. Raises ``RuntimeError`` if a configured connector
    name is missing from the context. Use ``open_connection=True`` for
    read-only state CLI tasks that don't go through the standard
    connector-loading flow; use ``open_connection=False`` for the
    executor path where connections are already opened by
    ``_load_data_connectors``.

    Profile precedence for each side is: the global ``override_profile_name``
    (the ``--profile-name`` CLI flag) when supplied, else the
    definition-level ``profile_name`` declared on the side's config, else
    the connection's default profile.
    """
    effective_state_backend_connector_config_wrapper = (
        build_effective_state_backend_connector_config_wrapper(
            namespaced_data_flow_definition=namespaced_data_flow_definition,
            execution_context=execution_context,
        )
    )
    if effective_state_backend_connector_config_wrapper is None:
        return None
    primary_state_backend_connector = _resolve_state_backend_connector_for_side(
        execution_context=execution_context,
        state_backend_connector_config=(
            effective_state_backend_connector_config_wrapper.primary
        ),
        state_backend_connector_side="primary",
        open_connection=open_connection,
        override_profile_name=override_profile_name,
    )
    secondary_state_backend_connector = (
        _resolve_state_backend_connector_for_side(
            execution_context=execution_context,
            state_backend_connector_config=(
                effective_state_backend_connector_config_wrapper.secondary
            ),
            state_backend_connector_side="secondary",
            open_connection=open_connection,
            override_profile_name=override_profile_name,
        )
        if effective_state_backend_connector_config_wrapper.secondary is not None
        else None
    )
    return StateBackendConnectorWrapper(
        primary=primary_state_backend_connector,
        secondary=secondary_state_backend_connector,
    )


def _resolve_state_backend_connector_for_side(
    execution_context: NldExecutionContext,
    state_backend_connector_config: ConnectorConfig,
    state_backend_connector_side: Literal["primary", "secondary"],
    open_connection: bool,
    override_profile_name: str | None = None,
) -> StateBackendConnector:
    # The side string is used only to make the error message explicit.
    connection_name = state_backend_connector_config.connector
    # CLI flag wins over the definition-level profile pinned on the side.
    effective_profile_name = (
        override_profile_name
        if override_profile_name is not None
        else state_backend_connector_config.profile_name
    )
    available_data_connector_names = set(
        execution_context.get_available_data_connector_names()
    )
    # Read-only state CLI tasks don't pre-load connectors via
    # ``_load_data_connectors``; fall back to the connection configs so the
    # connector can be lazy-loaded by ``get_data_connector`` below.
    known_connection_names = set(
        execution_context.connection_configs.get_connection_names()
    )
    if (
        connection_name not in available_data_connector_names
        and connection_name not in known_connection_names
    ):
        raise RuntimeError(
            f"State backend connector '{connection_name}' "
            f"({state_backend_connector_side}) is not available in the "
            "flow execution context but was requested for flow execution."
        )
    data_connector = execution_context.get_data_connector(
        name=connection_name,
        profile_name=effective_profile_name,
        open_connection=open_connection,
    )
    return StateBackendConnector(
        data_connector=data_connector,
        config=state_backend_connector_config,
    )
