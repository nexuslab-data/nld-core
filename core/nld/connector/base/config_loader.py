from typing import Any

from nld.utils.mixin import NldMixIn

from .config import (
    ConnectionConfig,
    ConnectionConfigs,
)
from .config_source import ConnectionConfigSource


class ConnectionConfigLoader(NldMixIn):
    """
    Manages multiple connection configuration sources and merges them with precedence.

    Higher priority sources override lower priority sources.
    Within each connection, parameters and profiles are merged separately.
    """

    def __init__(self, sources: list[ConnectionConfigSource]):
        """
        Initialize the connection config loader.

        Args:
            sources: List of connection config sources
        """
        super().__init__()
        self.sources = sorted(sources, key=lambda s: s.get_priority())

    def load(self) -> ConnectionConfigs:
        """
        Load and merge configurations from all available sources.

        Sources are processed in priority order (lowest to highest).
        Higher priority sources override values from lower priority sources.

        Returns:
            Merged ConnectionConfigs object

        Raises:
            ValueError: If no configurations could be loaded from any source
        """
        merged_data: dict[str, dict[str, Any]] = {}

        # Load from all sources in priority order (lowest to highest)
        for source in self.sources:
            if not source.is_available():
                continue

            configs = source.load()
            if configs is None:
                continue

            # Merge each connection config
            for connection_name in configs.get_connection_names():
                config = configs.get_connection_config(connection_name)

                if connection_name not in merged_data:
                    # First time seeing this connection
                    merged_data[connection_name] = {
                        "type": config.type,
                        "custom_connector": config.custom_connector,
                        "default_profile": config.default_profile.copy(),
                        "profiles": {
                            name: params.copy()
                            for name, params in config.profiles.items()
                        },
                    }
                else:
                    # Merge with existing connection data
                    existing = merged_data[connection_name]

                    # Override type if provided
                    if config.type:
                        existing["type"] = config.type

                    # Override custom_connector if provided
                    if config.custom_connector:
                        existing["custom_connector"] = config.custom_connector

                    # Merge default_profile (higher priority overrides)
                    existing["default_profile"].update(config.default_profile)

                    # Merge profiles
                    for profile_name, profile_params in config.profiles.items():
                        if profile_name not in existing["profiles"]:
                            existing["profiles"][profile_name] = profile_params.copy()
                        else:
                            # Merge profile parameters
                            existing["profiles"][profile_name].update(profile_params)

        if not merged_data:
            self.log_warn("No connection configurations loaded from any sources.")

        # Build final ConnectionConfigs object
        connections: dict[str, ConnectionConfig] = {}

        for connection_name, data in merged_data.items():
            connections[connection_name] = ConnectionConfig(
                name=connection_name,
                type=data.get("type", ""),
                default_profile=data.get("default_profile", {}),
                profiles=data.get("profiles", {}),
                custom_connector=data.get("custom_connector"),
            )

        return ConnectionConfigs(configs=connections)

    def load_from_connection_name(self, connection_name: str) -> ConnectionConfig:
        """
        Load configuration for a specific connection.

        Args:
            connection_name: Name of the connection to load

        Returns:
            ConnectionConfig for the specified connection

        Raises:
            ValueError: If connection not found in any source
        """
        all_configs = self.load()
        return all_configs.get_connection_config(connection_name)
