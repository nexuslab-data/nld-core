from typing import Any

from nld.pydantic import NldBaseModel


class ConnectorConfig(NldBaseModel):
    """A flow's reference to a connection: name plus optional profile and params.

    Holds the connection name in ``connector`` and a free-form ``params``
    dict consumed by the backend manager class (backend-specific knobs
    like ``file_format`` live there so each backend owns its own
    parameter contract). ``profile_name`` optionally pins the credential
    profile used to open the connection; it is the definition-level
    default and is overridden by the global ``--profile-name`` CLI flag
    when one is supplied.

    The same model types both the per-side state backend configuration
    and each entry of a flow's ``data_connectors`` mapping, so a flow can
    pin a profile per connection in either place. Containers that hold a
    ``ConnectorConfig`` accept a bare connection-name string and coerce it
    via ``coerce_connector_config``.
    """

    connector: str
    profile_name: str | None = None
    params: dict[str, Any] = {}


def coerce_connector_config(value: Any) -> Any:
    """Promote a bare connection-name string to a ``ConnectorConfig`` dict.

    Lets ``data_connectors`` entries and state-backend sides be written as
    just the connection name while still resolving to a full
    ``ConnectorConfig``.
    """
    if isinstance(value, str):
        return {"connector": value}
    return value
