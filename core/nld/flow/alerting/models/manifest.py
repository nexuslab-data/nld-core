from pydantic import field_validator

from nld.pydantic import NldBaseModel


class FlowAlertTransportManifest(NldBaseModel):
    """Declarative descriptor locating an external alert transport.

    Carries the dotted import path of a ``FlowAlertTransport`` subclass so a
    platform can register its own technology from ``nld_project.yml``
    (``flow.additional_alert_transports``) without nld-core knowing about
    it. Holds no imported Python types, so it can be populated from YAML
    before its target module is loadable — the class is imported the first
    time the registry looks the name up, never at project load.
    """

    name: str
    transport_class: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("name must be a non-empty string")
        return value

    @field_validator("transport_class")
    @classmethod
    def validate_transport_class_format(cls, value: str) -> str:
        """Validate transport_class contains a dot (module.ClassName format)."""
        if "." not in value:
            raise ValueError(
                f"Invalid transport_class '{value}': "
                f"expected 'module.path.ClassName' format"
            )
        return value
