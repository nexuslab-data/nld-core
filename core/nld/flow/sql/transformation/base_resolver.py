import abc
import importlib

from nld.flow.definition.sql_config import SQLConfig
from nld.flow.sql.transformation.base import SQLRenderingTransformation
from nld.logging.logger import log_debug_default


class TransformationResolver(abc.ABC):
    """Base resolver for a single SQL transformation type.

    Each concrete resolver declares its transformation name, the
    default builtin class, and the dotted path to its connector
    subpackage. The resolver handles connector-specific override
    discovery via lazy module import.
    """

    @property
    @abc.abstractmethod
    def transformation_name(self) -> str:
        """Uppercase name identifier (e.g. 'SELECT')."""

    @property
    @abc.abstractmethod
    def builtin_class(self) -> type[SQLRenderingTransformation]:
        """The default transformation class this resolver provides."""

    @property
    @abc.abstractmethod
    def connector_package(self) -> str:
        """Full dotted path to the connector subpackage.

        Example: 'nld.flow.sql.transformation.select.connector'
        """

    def create_builtin(
        self,
        config: SQLConfig | None = None,
    ) -> SQLRenderingTransformation:
        """Instantiate the default transformation."""
        return self.builtin_class(config=config)

    def find_connector_override(
        self,
        connector_type: str,
    ) -> type[SQLRenderingTransformation] | None:
        """Lazy-import connector module and return override class if found.

        Attempts to import {connector_package}.{connector_type} and
        scans for concrete SQLRenderingTransformation subclasses.
        Returns the first matching class or None.
        """
        module_path = f"{self.connector_package}.{connector_type}"
        try:
            module = importlib.import_module(module_path)
            log_debug_default(
                f"Loaded connector transformation module: {module_path}",
            )
        except ModuleNotFoundError:
            log_debug_default(
                f"No connector transformation module found at {module_path}",
            )
            return None

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, SQLRenderingTransformation)
                and attr is not SQLRenderingTransformation
                and attr is not self.builtin_class
            ):
                return attr
        return None
