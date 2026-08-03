from pydantic import field_validator

from nld.pydantic import NldBaseModel


class DataQualityRuleManifest(NldBaseModel):
    """Declarative descriptor locating an external data quality rule.

    Carries the dotted import path of a ``DataQualityRule`` subclass so a
    project can register additional rules from ``nld_project.yml`` without
    committing to a hardcoded layout. Holds no imported Python types, so it
    can be populated from YAML before its target module is loadable.
    """

    name: str
    rule_class: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("name must be a non-empty string")
        return value

    @field_validator("rule_class")
    @classmethod
    def validate_rule_class_format(cls, value: str) -> str:
        """Validate rule_class contains a dot (module.ClassName format)."""
        if "." not in value:
            raise ValueError(
                f"Invalid rule_class '{value}': "
                "must be a fully qualified Python path "
                "(e.g., 'my_package.quality.MyRule')"
            )
        return value
