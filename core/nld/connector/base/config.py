from typing import Any

from pydantic import Field

from nld.pydantic.base_model import NldBaseModel
from nld.pydantic.named_base_model import NldNamedBaseModel

from .exceptions import (
    UnavailableConnectionConfigException,
    UnavailableConnectionProfileException,
)


class ConnectionConfig(NldNamedBaseModel):
    type: str
    default_profile: dict[str, Any]
    profiles: dict[str, dict[str, Any]] = Field(default_factory=dict)
    custom_connector: str | None = None

    def get_profile_names(self) -> list[str]:
        return list(self.profiles.keys())

    def get_available_profile_names(self) -> list[str]:
        """Return every selectable profile, including the implicit default.

        Parameters declared directly on the connection (without a named
        profile) are openable by passing no profile name, so they surface
        as "default" alongside the named profiles. Without this, a
        connection that also defines named profiles would hide its
        no-profile variant from listings.
        """
        available_profile_names: list[str] = []
        if self.default_profile:
            available_profile_names.append("default")
        available_profile_names.extend(self.get_profile_names())
        if not available_profile_names:
            available_profile_names.append("default")
        return available_profile_names

    def get_parameters_for_profile(
        self, profile_name: str | None = None
    ) -> dict[str, Any]:
        """
        Get parameters for a specific profile.

        If profile_name is None, returns the default_profile directly.
        Otherwise, merges default_profile with the specified profile,
        where profile values override default values.

        Args:
            profile_name: Optional profile name to retrieve

        Returns:
            Dictionary of parameters for the profile

        Raises:
            UnavailableConnectionProfileException: If profile not found
        """
        if profile_name is None:
            return self.default_profile.copy()

        if profile_name not in list(self.profiles.keys()):
            raise UnavailableConnectionProfileException(self.name, profile_name)

        merged_params = self.default_profile.copy()
        merged_params.update(self.profiles[profile_name])
        return merged_params


class ConnectionConfigs(NldBaseModel):
    configs: dict[str, ConnectionConfig]

    def get_connection_names(self) -> list[str]:
        return list(self.configs.keys())

    def get_connection_config(self, connection_name: str) -> ConnectionConfig:
        if connection_name not in list(self.configs.keys()):
            raise UnavailableConnectionConfigException(connection_name)
        return self.configs[connection_name]

    def get_connection_types(self) -> list[str]:
        return list(set([config.type for config in self.configs.values()]))

    @classmethod
    def from_toml(cls, toml_content: str) -> "ConnectionConfigs":
        """
        Parse TOML configuration and create ConnectionConfigs object.

        TOML structure:
            [connection_name]
            type = "connection_type"
            param1 = "value1"
            param2 = "value2"

            [profile_name.connection_name]
            param1 = "override_value1"

        Args:
            toml_content: TOML string content

        Returns:
            ConnectionConfigs object with all connections and profiles
        """
        import tempfile

        from nld.connector.base.config_source import (
            TomlConnectionConfigSource,
        )

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".toml",
            delete=False,
        ) as f:
            f.write(toml_content)
            temp_path = f.name

        try:
            source = TomlConnectionConfigSource(temp_path)
            result = source.load()
            if result is None:
                raise ValueError("Failed to parse TOML content")
            return result
        finally:
            import os

            os.unlink(temp_path)

    @classmethod
    def from_sources(cls, root_folder_path: str) -> "ConnectionConfigs":
        """
        Load connection configurations from multiple sources with precedence.

        Sources (in priority order, lowest to highest):
        1. secrets.toml file (priority: 10)
        2. Environment variables with NLD__DATA_CONNECTION prefix (priority: 20)

        Higher priority sources override lower priority sources.

        Args:
            root_folder_path: Root folder path for configuration files

        Returns:
            Merged ConnectionConfigs from all available sources

        Raises:
            ValueError: If no configurations could be loaded from any source
        """
        import os

        from nld.connector.base.config_loader import (
            ConnectionConfigLoader,
        )
        from nld.connector.base.config_source import (
            EnvironmentConnectionConfigSource,
            TomlConnectionConfigSource,
        )

        sources = [
            TomlConnectionConfigSource(
                file_path=os.path.join(root_folder_path, "secrets.toml"),
                priority=10,
                required=False,
            ),
            EnvironmentConnectionConfigSource(
                prefix="NLD__DATA_CONNECTION", priority=20
            ),
        ]

        loader = ConnectionConfigLoader(sources)
        return loader.load()
