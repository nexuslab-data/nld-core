"""Connection configuration sources for loading configs."""

import os
import tomllib
from abc import ABC, abstractmethod
from typing import Any

from .config import (
    ConnectionConfig,
    ConnectionConfigs,
)


class ConnectionConfigSource(ABC):
    """Abstract base class for connection configuration sources."""

    @abstractmethod
    def load(self) -> ConnectionConfigs | None:
        """
        Load connection configurations from this source.

        Returns:
            ConnectionConfigs object if source is available, None otherwise
        """

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this source is available.

        Returns:
            True if source can be loaded, False otherwise
        """

    @abstractmethod
    def get_priority(self) -> int:
        """
        Get the priority of this source (higher number = higher priority).

        Returns:
            Priority integer
        """


class TomlConnectionConfigSource(ConnectionConfigSource):
    """Load connection configurations from a TOML file."""

    def __init__(self, file_path: str, priority: int = 10, required: bool = False):
        """
        Initialize TOML connection config source.

        Args:
            file_path: Path to the TOML file
            priority: Priority of this source (default: 10)
            required: Whether this source must exist (default: False)
        """
        self.file_path = file_path
        self.priority = priority
        self.required = required

    def is_available(self) -> bool:
        """Check if TOML file exists."""
        return os.path.exists(self.file_path)

    def get_priority(self) -> int:
        """Get the priority of this source."""
        return self.priority

    def load(self) -> ConnectionConfigs | None:
        """
        Load connection configurations from TOML file.

        Returns:
            ConnectionConfigs object if file exists, None otherwise

        Raises:
            FileNotFoundError: If file doesn't exist and source is required
        """
        if not self.is_available():
            if self.required:
                raise FileNotFoundError(
                    f"Required TOML config file not found: {self.file_path}"
                )
            return None

        with open(self.file_path, "rb") as file:
            toml_content = file.read().decode("utf-8")

        return self._parse_toml(toml_content)

    def _parse_toml(self, toml_content: str) -> ConnectionConfigs:
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
        toml_data = tomllib.loads(toml_content)

        # Group sections by connection name
        connection_data: dict[str, dict[str, Any]] = {}

        # First pass: identify all connection names
        for section_name, section_data in toml_data.items():
            if isinstance(section_data, dict):
                # Check if this is a base connection
                has_nested_connections = any(
                    isinstance(v, dict) for v in section_data.values()
                )

                if not has_nested_connections or "type" in section_data:
                    # This is a base connection section
                    connection_name = section_name

                    if connection_name not in connection_data:
                        connection_data[connection_name] = {
                            "profiles": {},
                            "default_profile": {},
                        }

                    # Extract type and custom_connector if present
                    connection_data[connection_name]["type"] = section_data.get(
                        "type", ""
                    )
                    connection_data[connection_name]["custom_connector"] = (
                        section_data.get("custom_connector")
                    )

                    # All other fields become default_profile
                    default_profile = {
                        k: v
                        for k, v in section_data.items()
                        if k not in ["type", "custom_connector"]
                        and not isinstance(v, dict)
                    }
                    connection_data[connection_name]["default_profile"] = (
                        default_profile
                    )
                else:
                    # This is a profile section
                    profile_name = section_name
                    for connection_name, profile_data in section_data.items():
                        if connection_name not in connection_data:
                            connection_data[connection_name] = {
                                "profiles": {},
                                "default_profile": {},
                            }

                        connection_data[connection_name]["profiles"][profile_name] = (
                            profile_data if isinstance(profile_data, dict) else {}
                        )

        # Build ConnectionConfig objects
        connections: dict[str, ConnectionConfig] = {}

        for connection_name, data in connection_data.items():
            connections[connection_name] = ConnectionConfig(
                name=connection_name,
                type=data.get("type", ""),
                default_profile=data.get("default_profile", {}),
                profiles=data.get("profiles", {}),
                custom_connector=data.get("custom_connector"),
            )

        return ConnectionConfigs(configs=connections)


DATA_CONNECTION_ENV_VAR_PREFIX = "NLD__DATA_CONNECTION"


class EnvironmentConnectionConfigSource(ConnectionConfigSource):
    """Load connection configurations from environment variables."""

    def __init__(
        self, prefix: str = DATA_CONNECTION_ENV_VAR_PREFIX, priority: int = 20
    ):
        """
        Initialize environment variable connection config source.

        Environment variable format:
            {prefix}__{CONNECTION_NAME}__{PARAM}=value
            {prefix}__{CONNECTION_NAME}__{PROFILE_NAME}__{PARAM}=value

        Example:
            NLD__DATA_CONNECTION__SNOW_OPENDATA__TYPE=snowflake
            NLD__DATA_CONNECTION__SNOW_OPENDATA__STAGING__DATABASE=OPENDATA_STAGING

        Args:
            prefix: Prefix for environment variables (default: NLD__DATA_CONNECTION)
            priority: Priority of this source (default: 20, higher than TOML)
        """
        self.prefix = prefix
        self.priority = priority

    def is_available(self) -> bool:
        """Check if any relevant environment variables exist."""
        for key in os.environ:
            if key.startswith(self.prefix):
                return True
        return False

    def get_priority(self) -> int:
        """Get the priority of this source."""
        return self.priority

    def load(self) -> ConnectionConfigs | None:
        """
        Load connection configurations from environment variables.

        Returns:
            ConnectionConfigs object if env vars exist, None otherwise
        """
        if not self.is_available():
            return None

        # Group environment variables by connection
        connection_data: dict[str, dict[str, Any]] = {}

        for env_key, env_value in os.environ.items():
            if not env_key.startswith(self.prefix):
                continue

            # Parse the key structure
            parts = env_key[len(self.prefix) + 2 :].split("__")

            if len(parts) < 2:
                continue  # Invalid format

            connection_name = parts[0].lower()

            # Initialize connection data if needed
            if connection_name not in connection_data:
                connection_data[connection_name] = {
                    "profiles": {},
                    "default_profile": {},
                    "type": "",
                }

            if len(parts) == 2:
                # Default profile parameter
                param_name = parts[1].lower()

                if param_name == "type":
                    connection_data[connection_name]["type"] = env_value
                elif param_name == "custom_connector":
                    connection_data[connection_name]["custom_connector"] = env_value
                else:
                    connection_data[connection_name]["default_profile"][param_name] = (
                        env_value
                    )

            elif len(parts) == 3:
                # Profile-specific parameter
                profile_name = parts[1].lower()
                param_name = parts[2].lower()

                if profile_name not in connection_data[connection_name]["profiles"]:
                    connection_data[connection_name]["profiles"][profile_name] = {}

                connection_data[connection_name]["profiles"][profile_name][
                    param_name
                ] = env_value

        # Build ConnectionConfig objects
        connections: dict[str, ConnectionConfig] = {}

        for connection_name, data in connection_data.items():
            connections[connection_name] = ConnectionConfig(
                name=connection_name,
                type=data.get("type", ""),
                default_profile=data.get("default_profile", {}),
                profiles=data.get("profiles", {}),
                custom_connector=data.get("custom_connector"),
            )

        return ConnectionConfigs(configs=connections)
