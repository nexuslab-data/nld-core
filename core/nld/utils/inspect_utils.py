from inspect import getmembers, isclass
from types import ModuleType, UnionType
from typing import Any, Union, get_args, get_origin

from nld.exceptions import ImplementationException


def extract_functions_from_command_module(
    command_module: ModuleType, command_prefix: str, command_type: type
) -> list[Any]:
    return [
        command[1]
        for command in getmembers(command_module)
        if command[0].startswith(command_prefix) and type(command[1]) is command_type
    ]


def find_subclass_in_module(
    module: ModuleType,
    base_class: type,
) -> type:
    """
    Find a class in a module that inherits from the specified base class.

    Args:
        module: The module to search in
        base_class: The base class to look for

    Raises:
        ImplementationException: If no class is found in the module

    Returns:
        The first class found that inherits from base_class and is defined
        in the module (not imported)
    """
    for _name, obj in getmembers(module, isclass):
        if (
            obj is not base_class
            and isinstance(obj, type)
            and issubclass(obj, base_class)
            and obj.__module__ == module.__name__
        ):
            return obj
    raise ImplementationException(
        f"No {base_class.__name__} found in module '{module.__name__}'"
    )


def get_method_param_type_hints(
    cls: type[Any],
    method_name: str,
) -> dict[str, type[Any]]:
    """
    Extract parameter type hints from a class method.

    Retrieves type annotations from the specified method, excluding 'self',
    'return', and **kwargs parameters. For Optional types, extracts the
    inner type.

    Args:
        cls: The class containing the method.
        method_name: Name of the method to inspect.

    Returns:
        Dictionary mapping parameter names to their resolved types.

    Example:
        >>> class MyTask:
        ...     def __init__(self, config: MyConfig, name: str): ...
        >>> get_method_param_type_hints(MyTask, "__init__")
        {'config': MyConfig, 'name': str}
    """
    method = getattr(cls, method_name, None)
    if method is None:
        return {}

    annotations = getattr(method, "__annotations__", {})
    result: dict[str, type[Any]] = {}

    for param_name, param_type in annotations.items():
        if param_name in ("return", "self", "kwargs", "args"):
            continue

        resolved_type = unwrap_optional_type(param_type)
        if resolved_type is not None:
            result[param_name] = resolved_type

    return result


def unwrap_optional_type(type_hint: Any) -> type[Any] | None:
    """
    Unwrap Optional and union types to get the inner non-None type.

    Handles Optional[T], T | None, and None | T patterns.
    For non-optional types, returns the type as-is. Returns None if
    the type cannot be resolved to a concrete type.

    Args:
        type_hint: The type annotation to unwrap.

    Returns:
        The unwrapped type, or None if not resolvable.

    Example:
        >>> unwrap_optional_type(Optional[MyModel])
        MyModel
        >>> unwrap_optional_type(str)
        str
    """
    origin = get_origin(type_hint)

    if origin is Union or isinstance(type_hint, UnionType):
        args = get_args(type_hint)
        non_none_args = [arg for arg in args if arg is not type(None)]
        if len(non_none_args) == 1:
            return non_none_args[0]  # type: ignore[no-any-return]
        elif len(non_none_args) > 1:
            return None
        return None

    if origin is not None:
        return type_hint  # type: ignore[no-any-return]

    if isinstance(type_hint, type):
        return type_hint

    return None
