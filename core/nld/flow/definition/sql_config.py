from typing import Any

from pydantic import field_validator

from nld.pydantic import NldBaseModel


class SQLConfig(NldBaseModel):
    """SQL-specific configuration for a data flow definition.

    Groups SQL rendering transformation settings alongside
    pre-hook and post-hook statements that execute before and
    after the main flow SQL.
    """

    parameters: dict[str, Any] | None = None
    post_hook: list[str] | None = None
    pre_hook: list[str] | None = None
    no_rendering: bool = False
    transformation: str | None = None

    @field_validator("pre_hook", "post_hook", mode="before")
    @classmethod
    def wrap_string_as_list(cls, value: list[str] | str | None) -> list[str] | None:
        """Normalize a single string into a one-element list."""
        if isinstance(value, str):
            return [value]
        return value
