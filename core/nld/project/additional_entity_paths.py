import os
from importlib.resources import files
from importlib.resources.abc import Traversable

from .project_exceptions import NldProjectError

PACKAGE_ENTITY_PATH_SCHEME = "pkg://"


def _resolve_package_entity_path(entity_path: str) -> str:
    """Resolve a ``pkg://<package>/<subdir>`` URI to a filesystem directory.

    The package is imported, so this only works for packages installed in the
    running interpreter. Zipped distributions are rejected explicitly rather
    than silently yielding nothing: entity loading walks real directories.
    """
    reference = entity_path[len(PACKAGE_ENTITY_PATH_SCHEME) :]
    package_name, _, sub_path = reference.partition("/")
    if not package_name:
        raise NldProjectError(
            f"Invalid package entity path '{entity_path}': expected "
            f"'{PACKAGE_ENTITY_PATH_SCHEME}<python_package>[/<subdirectory>]'"
        )

    try:
        package_root: Traversable = files(package_name)
    except (ImportError, TypeError) as error:
        raise NldProjectError(
            f"Cannot resolve package entity path '{entity_path}': "
            f"package '{package_name}' is not importable ({error})"
        ) from error

    resolved: Traversable = package_root
    for part in sub_path.split("/"):
        if part:
            resolved = resolved.joinpath(part)

    if not isinstance(resolved, os.PathLike):
        raise NldProjectError(
            f"Package entity path '{entity_path}' does not resolve to a "
            f"filesystem directory. Entities cannot be loaded from a zipped "
            f"or namespace distribution."
        )
    return os.path.normpath(str(os.fspath(resolved)))


def resolve_additional_entity_paths(
    entity_paths: list[str],
    root_folder_path: str,
) -> list[str]:
    """Resolve declared additional entity roots to existing directories.

    Accepts filesystem paths, absolute or relative to the project root, and
    ``pkg://<python_package>/<subdirectory>`` URIs pointing at entities shipped
    inside an installed package. Order is preserved: it is the precedence order
    the entity registry applies, the project root always winning last.
    """
    resolved_paths: list[str] = []
    for entity_path in entity_paths:
        if entity_path.startswith(PACKAGE_ENTITY_PATH_SCHEME):
            resolved_path = _resolve_package_entity_path(entity_path=entity_path)
        elif os.path.isabs(entity_path):
            resolved_path = os.path.normpath(entity_path)
        else:
            resolved_path = os.path.normpath(
                os.path.join(root_folder_path, entity_path)
            )

        if not os.path.isdir(resolved_path):
            raise NldProjectError(
                f"Additional entity path '{entity_path}' does not exist or is "
                f"not a directory (resolved to '{resolved_path}')"
            )
        if resolved_path not in resolved_paths:
            resolved_paths.append(resolved_path)

    return resolved_paths
