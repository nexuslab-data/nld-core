from nld.pydantic import NldNamedBaseModel


class ExecutionParameterDefinition(NldNamedBaseModel):
    short_name: str | None = None
    data_type: str = "str"
    mandatory: bool = True
    default_value: str | None = None
    allowed_values: list[str] | None = None
    help_text: str = ""
