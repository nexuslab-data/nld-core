import contextvars
import os
import uuid
from typing import Any, Optional

from nld.connector.base import ConnectionConfigs, DataConnector
from nld.connector.manager import ConnectorFactory
from nld.logging.logger import NldLoggable
from nld.project import Project
from nld.service import FileOutputService
from nld.service.nld_entity_registry import NldEntityRegistry
from nld.task.context.env_var import (
    CONFIG_FOLDER_PATH_ENV_VAR,
    ROOT_FOLDER_PATH_ENV_VAR,
)
from nld.task.context.request import TaskRequest
from nld.task.execution import ExecutionInfo
from nld.utils.datetime_util import get_current_datetime
from nld.utils.file_util import join_paths

# Context variable for storing the flow execution context
_nld_execution_context: contextvars.ContextVar[Optional["NldExecutionContext"]] = (
    contextvars.ContextVar("nld_execution_context", default=None)
)


class NldExecutionContext(NldLoggable):
    """Context object holding connections and current nld run information.

    This context is accessible throughout task execution without needing
    to pass it as an argument. Uses Python's contextvars to provide
    thread-safe and async-safe access to execution information.
    """

    def __init__(
        self,
        task_request: TaskRequest,
        with_project: bool = False,
    ):
        super().__init__()
        self.task_request = task_request
        self.exec_info = ExecutionInfo(
            completion_label=self.task_request.completion_label,
            exec_name=self.task_request.execution_name,
            uuid=str(uuid.uuid4()),
            started_at=get_current_datetime(),
        )

        self.nld_config_folder_path = self.get_nld_config_folder_path()
        self.connection_configs = ConnectionConfigs.from_sources(
            self.nld_config_folder_path
        )
        self.connector_factory = self.init_connector_factory()
        self._file_output_service: FileOutputService | None = None
        self._project: Project | None = None
        if with_project:
            self.init_project()

    def init_project(self) -> None:
        self._project = Project.from_yaml(
            root_path=self.get_nld_root_folder_path(),
            load_entities=False,
        )

    @property
    def project(self) -> Project:
        """Get project instance

        Raises:
            RuntimeError: if the project was not initialized
        """
        if self._project is None:
            raise RuntimeError("Project is not available in the context")
        return self._project

    def load_entities(self, force_reload: bool = False) -> None:
        """Load entities into project's entity registry."""
        self.project.load_entities(force_reload=force_reload)

    @property
    def entity_registry(self) -> NldEntityRegistry:
        """Get entity registry from project."""
        return self.project.entity_registry

    def get_nld_config_folder_path(self) -> str:
        return os.path.abspath(
            self.task_request.nld_config_folder_path
            or os.getenv(CONFIG_FOLDER_PATH_ENV_VAR)
            or join_paths(os.getcwd(), ".nld")
            or os.getcwd()
        )

    @property
    def file_output_service(self) -> FileOutputService:
        """Get the file output service for this execution context."""
        if self._file_output_service is None:
            self._file_output_service = FileOutputService(
                root_folder_path=self.get_nld_root_folder_path(),
                override_output_folder_path=self.resolve_output_folder_path(),
            )
        return self._file_output_service

    def resolve_output_folder_path(self) -> str | None:
        """Resolve the output folder path from task request parameters.

        Reads output_in_project and output_folder_name from the task
        request parameters and returns the appropriate output path.
        """
        parameters = self.task_request.get_parameters()
        if parameters.get("output_in_project", False):
            return self.project.entities_root_folder_path
        output_folder_name: str | None = parameters.get("output_folder_name")
        if output_folder_name:
            return output_folder_name
        return None

    def get_nld_root_folder_path(self) -> str:
        return os.path.abspath(
            self.task_request.nld_root_folder_path
            or os.getenv(ROOT_FOLDER_PATH_ENV_VAR)
            or os.getcwd()
        )

    @staticmethod
    def init_connector_factory() -> ConnectorFactory:
        """Initialize the connector factory without preloading plugins.

        Plugins are loaded lazily when connectors are requested, avoiding
        unnecessary imports of connector modules and their dependencies.
        """
        return ConnectorFactory()

    def load_connector(self, name: str, profile_name: str | None = None) -> None:
        if self.connector_factory.connector_manager.has_connector(name):
            raise RuntimeError(
                f"Connector {name} already exists and cannot be reloaded."
            )
        connection_config = self.connection_configs.get_connection_config(
            connection_name=name
        )
        self.connector_factory.load_connector(
            connection_config,
            profile_name=profile_name,
        )

    def get_available_data_connector_names(self) -> list[str]:
        return list(self.connector_factory.connector_manager.connectors.keys())

    def get_data_connector(
        self,
        name: str,
        profile_name: str | None = None,
        open_connection: bool = True,
    ) -> DataConnector[Any]:
        if not self.connector_factory.connector_manager.has_connector(name):
            self.load_connector(
                name,
                profile_name=profile_name,
            )
        data_connector = self.connector_factory.connector_manager.get_connector(name)
        if open_connection and not data_connector.connection_is_opened():
            data_connector.open_connection()
        return data_connector

    def set_current(self) -> None:
        """Set this context as current nld execution context.

        Makes this context accessible via NldExecutionContext.get_current()
        method throughout nld execution.
        """
        _nld_execution_context.set(self)
        exec_name = self.task_request.execution_name
        self.log_debug(f"NLD execution context set for execution: {exec_name}.")

    @classmethod
    def get_current(cls) -> Optional["NldExecutionContext"]:
        """Get the current nld execution context."""
        return _nld_execution_context.get()

    @classmethod
    def require_current(cls) -> "NldExecutionContext":
        """Get the current nld execution context, raising an error if not set."""
        context = cls.get_current()
        if context is None:
            raise RuntimeError(
                "No nld execution context is currently set. "
                "Make sure to call context.set_current() before accessing it."
            )
        return context

    @classmethod
    def clear_current(cls) -> None:
        """Clear current nld execution context.

        Should be called at end of nld execution to clean up.
        """
        _nld_execution_context.set(None)

    def __enter__(self) -> "NldExecutionContext":
        """Enter context manager and set this as current context."""
        self.set_current()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit context manager and clear the current context."""
        self.clear_current()
