from __future__ import annotations

from pydantic import field_validator

from nld.pydantic import NldNamedBaseModel
from nld.pydantic.namespaced_base_model_wrapper import (
    NldNamespacedBaseModelWrapper,
)
from nld.structure.field.field import FieldTemplate


class StructureTemplate(NldNamedBaseModel):
    """Reusable template that groups field templates and structure-level metadata.

    A StructureTemplate holds FieldTemplate entities directly and can
    carry tags and properties that get merged into structures
    referencing this template.
    """

    field_templates: list[FieldTemplate] = []
    post_deployment_sql_hook: list[str] | None = None
    pre_deployment_sql_hook: list[str] | None = None
    properties: dict[str, str] | None = None
    tags: list[str] = []

    @field_validator(
        "pre_deployment_sql_hook", "post_deployment_sql_hook", mode="before"
    )
    @classmethod
    def wrap_string_as_list(cls, value: list[str] | str | None) -> list[str] | None:
        """Normalize a single string into a one-element list."""
        if isinstance(value, str):
            return [value]
        return value


class NamespacedStructureTemplate(NldNamespacedBaseModelWrapper[StructureTemplate]):
    """StructureTemplate wrapped with namespace information."""
