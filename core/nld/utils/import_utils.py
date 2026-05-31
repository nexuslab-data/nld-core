import importlib
import sys
from types import ModuleType
from typing import Any

from nld.logging.logger import log_debug_default


def import_module(
    module_path: str,
    additional_paths: list[str] | None = None,
) -> ModuleType:
    """
    Import a module by its path, optionally adding additional paths to sys.path.

    Args:
        module_path: The dotted module path (e.g., "flows.source.my_flow")
        additional_paths: Optional list of additional paths to add to sys.path

    Returns:
        The imported module

    Raises:
        ModuleNotFoundError: If the module cannot be found
    """
    log_debug_default(f"Import of module {module_path} - Started")

    original_sys_path = sys.path.copy()
    try:
        if additional_paths:
            for path in additional_paths:
                if path not in sys.path:
                    sys.path.insert(0, path)

        module = importlib.import_module(module_path)
        log_debug_default(f"Import of module {module_path} - Completed successfully")
        return module
    finally:
        sys.path = original_sys_path


def import_class_inside_module(class_path: str) -> tuple[ModuleType, type[Any]]:
    log_debug_default(f"Import of class {class_path} - Started")
    if "." in class_path:
        module_name, class_name = class_path.rsplit(".", 1)
    else:
        raise RuntimeError(
            f"Class should be contained inside a module, but only the "
            f"name was provided ${class_path}"
        )

    module = importlib.import_module(module_name)
    class_type = getattr(module, class_name)

    log_debug_default(f"Import of class {class_path} - Completed successfully")

    return module, class_type
