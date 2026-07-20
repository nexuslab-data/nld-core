from nld.pydantic import NldNamedBaseModel


class EnvironmentVariableDefinition(NldNamedBaseModel):
    """A declared environment variable read from the process environment.

    ``name`` is the environment variable key. When the variable is absent,
    ``default`` is used; a ``required`` variable with neither a value nor a
    default makes resolution fail. ``secret`` marks a value that must never be
    printed (only its presence is reported), and ``description`` documents the
    variable.
    """

    required: bool = False
    default: str | None = None
    secret: bool = False
    description: str = ""
