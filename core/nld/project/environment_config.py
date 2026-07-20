import os
from typing import Any

from pydantic import Field

from nld.pydantic import NldBaseModel

from .project_exceptions import (
    NldEnvironmentError,
    NldUnknownEnvironmentError,
)

NLD_ENVIRONMENT_ENV_VAR = "NLD__ENVIRONMENT"


class EnvironmentConfig(NldBaseModel):
    """Configuration of a single named environment.

    An environment selects a connection profile (resolved through the existing
    connection profile mechanism) and may override project-level variables for
    that environment only.
    """

    connection_profile: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)


class EnvironmentsConfig(NldBaseModel):
    """Project-level set of named environments.

    Loaded from the ``environments`` block of ``nld_project.yml``. The active
    environment is resolved with the precedence ``--env`` flag (explicit) →
    ``NLD__ENVIRONMENT`` variable → ``default``.

    Example YAML:
        environments:
          default: prd
          values:
            dev:
              connection_profile: dev
              variables:
                schema_name: opendata_dev
            prd:
              connection_profile: default
    """

    default: str | None = None
    values: dict[str, EnvironmentConfig] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EnvironmentsConfig":
        """Build an EnvironmentsConfig from a project dict's ``environments`` block."""
        return cls.model_validate(raw or {})

    def get_environment_names(self) -> list[str]:
        """Return all declared environment names."""
        return list(self.values.keys())

    def has(self, name: str) -> bool:
        """Whether an environment with this name is declared."""
        return name in self.values

    def get(self, name: str) -> EnvironmentConfig:
        """Return a declared environment by name, raising when unknown."""
        if name not in self.values:
            raise NldUnknownEnvironmentError(
                environment=name,
                available=self.get_environment_names(),
            )
        return self.values[name]

    def resolve_name(self, requested: str | None = None) -> str:
        """Resolve the active environment name.

        Precedence: explicit ``requested`` (the ``--env`` flag) → the
        ``NLD__ENVIRONMENT`` environment variable → the declared ``default``.
        When environments are declared, the resolved name must be one of them.
        """
        candidate = requested or os.getenv(NLD_ENVIRONMENT_ENV_VAR) or self.default
        if candidate is None:
            raise NldEnvironmentError(
                "No environment specified: pass --env, set NLD__ENVIRONMENT, "
                "or declare environments.default in nld_project.yml"
            )
        if self.values and candidate not in self.values:
            raise NldUnknownEnvironmentError(
                environment=candidate,
                available=self.get_environment_names(),
            )
        return candidate
