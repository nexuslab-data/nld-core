from importlib import import_module
from typing import Any

from nld.connector.base import ConnectionConfig, ConnectionConfigs
from nld.connector.base.connector import DataConnector
from nld.connector.base.credential import BaseConnectionCredential
from nld.connector.base.plugin import ConnectorPlugin
from nld.exceptions import NldRuntimeException
from nld.utils.import_utils import import_class_inside_module
from nld.utils.mixin import NldMixIn

from .events import (
    ConnectorPluginImportError,
    ConnectorPluginLoadSuccessful,
)
from .manager import ConnectorManager


class ConnectorFactory(NldMixIn):
    def __init__(self, allowed_connector_paths: list[str] | None = None) -> None:
        super().__init__()
        self.plugins: dict[str, ConnectorPlugin[Any, Any, Any]] = {}
        self.connector_manager: ConnectorManager = ConnectorManager()
        self.allowed_connector_paths = (
            allowed_connector_paths if allowed_connector_paths else []
        )
        path_count = len(self.allowed_connector_paths)
        self.log_debug(f"ConnectorFactory initialized with {path_count} paths")

    def load_connectors(
        self,
        connection_configs: ConnectionConfigs,
        profile_name: str | None = None,
        connection_names: list[str] | None = None,
    ) -> ConnectorManager:
        connection_names = (
            connection_configs.get_connection_names()
            if connection_names is None
            else connection_names
        )
        for connection_name in connection_names:
            self.load_connector(
                connection_config=connection_configs.get_connection_config(
                    connection_name
                ),
                profile_name=profile_name,
            )
        return self.connector_manager

    def load_connector(
        self,
        connection_config: ConnectionConfig,
        profile_name: str | None = None,
    ) -> ConnectorManager:
        if not connection_config.type:
            raise NldRuntimeException(
                f"Connection type is empty or not configured for connection "
                f"'{connection_config.name}'."
            )
        if connection_config.type not in self.plugins:
            self.load_plugin(connection_config.type)
        self.connector_manager.add_connector(
            connection_config.name,
            connector=self.create_new_connector(
                connection_config=connection_config,
                profile_name=profile_name,
            ),
        )
        return self.connector_manager

    def load_plugin(
        self,
        connection_type: str,
    ) -> type[BaseConnectionCredential]:
        # If the plugin was already loaded, return it
        if connection_type in self.plugins:
            return self.plugins[connection_type].credentials_class

        # Try to load from default path first
        mod = self._try_load_plugin_from_default_path(connection_type)

        # If failed and we have allowed paths, try those
        if mod is None and self.allowed_connector_paths:
            mod = self._try_load_plugin_from_allowed_paths(connection_type)

        # If still failed, raise error
        if mod is None:
            self.log_event(
                ConnectorPluginImportError(
                    exc=f"Could not find connector type {connection_type}"
                )
            )
            raise NldRuntimeException(f"Could not find adapter type {connection_type}!")

        plugin: ConnectorPlugin[Any, Any, Any] = mod.Plugin
        self.plugins[connection_type] = plugin
        self.log_event(ConnectorPluginLoadSuccessful(type=connection_type))

        if plugin.structure_class_path:
            from nld.structure.structure.structure import Structure

            Structure.register_subclass(
                connector_type=connection_type,
                class_path=plugin.structure_class_path,
            )

        return plugin.credentials_class

    def _try_load_plugin_from_default_path(self, connection_type: str) -> Any | None:
        """Try to load plugin from default nld.connector path."""
        try:
            mod: Any = import_module(
                "." + connection_type,
                package="nld.connector",
            )
            self.log_debug(
                f"Successfully loaded connector {connection_type} from default path"
            )
            return mod
        except ModuleNotFoundError:
            self.log_debug(
                f"Could not load connector {connection_type} from default path"
            )
            return None

    def _try_load_plugin_from_allowed_paths(self, connection_type: str) -> Any | None:
        """Try to load plugin from allowed connector paths."""
        for allowed_path in self.allowed_connector_paths:
            try:
                mod: Any = import_module(
                    "." + connection_type,
                    package=allowed_path,
                )
                self.log_debug(
                    f"Successfully loaded connector {connection_type} "
                    f"from {allowed_path}"
                )
                return mod
            except ModuleNotFoundError:
                self.log_debug(
                    f"Could not load connector {connection_type} from {allowed_path}"
                )
                continue
        return None

    def get_plugin(self, connection_type: str) -> ConnectorPlugin[Any, Any, Any]:
        if connection_type in list(self.plugins.keys()):
            return self.plugins[connection_type]
        connection_types = ", ".join(list(self.plugins.keys()))

        message = (
            f"Invalid connection plugin type {connection_type}! "
            f"Must be one of {connection_types}"
        )
        raise NldRuntimeException(message)

    def load_connector_custom_class(self, connector_custom_class: str) -> type:
        assert connector_custom_class is not None

        try:
            module, connector_class = import_class_inside_module(connector_custom_class)
            if not issubclass(connector_class, DataConnector):
                raise ValueError(
                    f"Connector class {connector_class} must inherit from DataConnector"
                )
            return connector_class
        except (ImportError, AttributeError, ValueError) as e:
            self.logger.error(
                f"Failed to load connector class {connector_custom_class}: {str(e)}"
            )
            raise

    def create_new_connector(
        self,
        connection_config: ConnectionConfig,
        profile_name: str | None = None,
    ) -> DataConnector[Any]:
        assert connection_config is not None
        plugin = self.get_plugin(connection_config.type)
        custom_connector_class = None
        if connection_config.custom_connector is not None:
            custom_connector_class = self.load_connector_custom_class(
                connection_config.custom_connector
            )
        return plugin.create_new_connector(  # type: ignore[no-any-return]
            name=connection_config.name,
            credentials_dict=connection_config.get_parameters_for_profile(profile_name),
            custom_connector_class=custom_connector_class,
        )
