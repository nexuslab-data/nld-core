from types import ModuleType
from typing import Any

from nld.logging import NldLoggable
from nld.utils.import_utils import (
    import_class_inside_module,
    import_module,
)


class ModuleLoader(NldLoggable):
    """
    Module loader service for importing classes from modules.

    This class provides functionality to load classes dynamically based on
    their path, with support for trying multiple known paths if the direct
    import fails.
    """

    def __init__(self, additional_paths: list[str] | None = None) -> None:
        """
        Initialize the ModuleLoader with additional import paths.

        Args:
            additional_paths: List of additional paths to try when importing classes
        """
        super().__init__()
        self.additional_paths = additional_paths if additional_paths else []
        path_count = len(self.additional_paths)
        self.log_debug(f"ModuleLoader initialized with {path_count} additional paths")

    def load_module(
        self,
        module_path: str,
    ) -> ModuleType:
        """
        Load a module from a module path.

        Args:
            module_path: The module path to import (e.g., 'flows.namespace.flow_name')

        Returns:
            The imported module

        Raises:
            ModuleNotFoundError: If the module cannot be found
        """
        self.log_debug(f"Attempting to load module: {module_path}")
        module = import_module(
            module_path=module_path,
            additional_paths=self.additional_paths,
        )
        self.log_debug(f"Successfully loaded module: {module_path}")
        return module

    def load_class(
        self,
        path_or_class_name: str,
        try_to_import_from_additional_paths: bool = False,
    ) -> tuple[ModuleType, type[Any]]:
        """
        Load a class from a module path or class name.

        This method first attempts to import the class using the provided path.
        If that fails and try_to_import_from_additional_paths is True, it attempts
        to import the class by prepending each additional path.

        Args:
            path_or_class_name: Full module path or class name to import
            try_to_import_from_additional_paths: Whether to try additional
                paths on failure

        Returns:
            Tuple containing the module and class type

        Raises:
            RuntimeError: If the class cannot be imported
        """
        self.log_debug(f"Attempting to load class: {path_or_class_name}")

        is_full_path = self._is_full_path(path_or_class_name)
        full_path_exception: Exception | None = None

        if is_full_path:
            try:
                module, class_type = import_class_inside_module(path_or_class_name)
                self.log_debug(
                    f"Successfully imported {path_or_class_name} from full path"
                )
                return module, class_type
            except Exception as e:
                if not try_to_import_from_additional_paths:
                    raise RuntimeError(
                        f"Failed to import class from full path "
                        f"{path_or_class_name}: {str(e)}"
                    ) from e
                full_path_exception = e
                self.log_debug(
                    f"Full path import failed for {path_or_class_name}, "
                    "trying known paths"
                )

        if not is_full_path or try_to_import_from_additional_paths:
            class_name = self._extract_class_name(path_or_class_name)
            try:
                return self._try_import_from_additional_paths(class_name)
            except Exception as fallback_exc:
                # Chain the original FQN failure so the actionable error (often
                # a transitive import or runtime bug) is not hidden behind the
                # additional-paths fallback message.
                if full_path_exception is not None:
                    raise fallback_exc from full_path_exception
                raise

        raise RuntimeError(
            f"Failed to import class {path_or_class_name} from any known path"
        )

    @staticmethod
    def _is_full_path(path_or_class_name: str) -> bool:
        """
        Check if the provided string is a full module path.

        A full path contains at least one dot, indicating module hierarchy.

        Args:
            path_or_class_name: The string to check

        Returns:
            True if it appears to be a full path, False otherwise
        """
        return "." in path_or_class_name

    @staticmethod
    def _extract_class_name(path_or_class_name: str) -> str:
        """
        Extract the class name from a full path or return the name as-is.

        If the provided name contains dots, extract just the final class name.
        Otherwise, return the name unchanged.

        Args:
            path_or_class_name: The class name or path

        Returns:
            The extracted class name

        Example:
            >>> ModuleLoader._extract_class_name("module.SubModule.ClassName")
            'ClassName'
            >>> ModuleLoader._extract_class_name("ClassName")
            'ClassName'
        """
        if "." in path_or_class_name:
            return path_or_class_name.rsplit(".", 1)[-1]
        return path_or_class_name

    def _try_import_from_additional_paths(
        self, class_name: str
    ) -> tuple[ModuleType, type[Any]]:
        """
        Try to import a class by prepending each additional path.

        Args:
            class_name: The class name to import

        Returns:
            Tuple containing the module and class type

        Raises:
            RuntimeError: If class cannot be imported from any additional path
        """
        last_exception = None

        for additional_path in self.additional_paths:
            full_path = f"{additional_path}.{class_name}"
            self.log_debug(f"Trying to import from: {full_path}")

            try:
                module, class_type = import_class_inside_module(full_path)
                self.log_debug(
                    f"Successfully imported {class_name} from {additional_path}"
                )
                return module, class_type
            except Exception as e:
                last_exception = e
                self.log_debug(f"Failed to import from {full_path}: {str(e)}")

        path_count = len(self.additional_paths)
        raise RuntimeError(
            f"Failed to import class {class_name} from any of the "
            f"{path_count} additional paths. Last error: {str(last_exception)}"
        ) from last_exception
