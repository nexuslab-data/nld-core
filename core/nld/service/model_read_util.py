import os
from pathlib import Path
from typing import Any

from nld.exceptions import BaseModelReadException
from nld.logging import (
    StandardDebugEvent,
    StandardTestEvent,
    log_event_default,
)
from nld.pydantic import NldBaseModel, NldNamedBaseModel
from nld.utils import file_util
from nld.utils.file_util import load_file_into_dict
from nld.utils.jinja_utils import JINJA2_FILE_STANDARD_REGEX
from nld.utils.yaml_util import (
    YAML_FILE_STANDARD_REGEX,
    load_yaml_file_into_dict,
)

from .events import (
    DataClassReadFromDirectoryCompletedSuccessfullyEvent,
    DataClassReadFromDirectoryStartEvent,
)


def _resolve_entity_class(
    base_model_type: type[NldBaseModel],
    entity_dict: dict[str, Any],
) -> type[NldBaseModel]:
    """Resolve the correct entity subclass based on YAML content.

    Resolution priority:
    1. Explicit ``class_path`` attribute in the entity dict.
    2. Registry lookup via ``get_registry_attribute_key`` /
       ``get_registered_class_path`` (e.g. connector_type registry).
    3. Falls back to ``base_model_type`` unchanged.

    Args:
        base_model_type: The default model type from the entity definition.
        entity_dict: The parsed YAML content dictionary.

    Returns:
        The resolved model type to instantiate.
    """
    from nld.utils.import_utils import import_class_inside_module

    # Priority 1: explicit class_path override
    explicit_class_path = entity_dict.get("class_path")
    if explicit_class_path:
        _, resolved_class = import_class_inside_module(explicit_class_path)
        if issubclass(resolved_class, base_model_type):
            return resolved_class
        return base_model_type

    # Priority 2: connector_type registry lookup
    get_registry_key = getattr(
        base_model_type,
        "get_registry_attribute_key",
        None,
    )
    if get_registry_key is None or not callable(get_registry_key):
        return base_model_type

    attribute_key = get_registry_key()
    if not attribute_key:
        return base_model_type

    get_registered = getattr(
        base_model_type,
        "get_registered_class_path",
        None,
    )
    if get_registered is None or not callable(get_registered):
        return base_model_type

    registry_key_value = entity_dict.get(attribute_key)
    if not registry_key_value:
        return base_model_type

    registered_path = get_registered(registry_key_value)
    if not registered_path:
        return base_model_type

    _, resolved_class = import_class_inside_module(registered_path)
    if issubclass(resolved_class, base_model_type):
        return resolved_class

    return base_model_type


def read_entities_from_local_directory(
    data_class: type[NldBaseModel],
    root_path: str,
) -> dict[str, NldNamedBaseModel | NldBaseModel]:
    """
    Read NldBaseModel objects from a local directory.

    Args:
        data_class: NldBaseModel or NldNamedBaseModel class type
        root_path: Directory to search for YAML files

    Returns:
        Dictionary mapping entity names to instances
    """
    definitions: dict[str, NldNamedBaseModel | NldBaseModel] = {}

    log_event_default(
        DataClassReadFromDirectoryStartEvent(data_class=data_class, root_path=root_path)
    )

    is_named = issubclass(data_class, NldNamedBaseModel)

    for file_path in file_util.get_list_of_files_in_cur_folder(
        root_path, YAML_FILE_STANDARD_REGEX
    ):
        try:
            entity_dict = load_yaml_file_into_dict(file_path)
            if is_named and "name" not in entity_dict:
                entity_dict["name"] = Path(file_path).stem
            resolved_type = _resolve_entity_class(
                data_class,
                entity_dict=entity_dict,
            )
            definition = resolved_type.from_dict(
                from_dict=entity_dict,
            )

            if is_named:
                key = definition.name  # type: ignore[attr-defined]
            else:
                key = Path(file_path).stem

            definitions.update({key: definition})
        except BaseModelReadException as e:
            file_name = os.path.basename(file_path)
            log_event_default(
                StandardDebugEvent(
                    msg=f"Error on the {data_class.__name__} file: {file_name}"
                )
            )
            raise e

    loaded_names = ", ".join(list(definitions.keys()))
    log_event_default(
        StandardTestEvent(msg=f"{data_class.__name__} loaded are: {loaded_names}")
    )
    log_event_default(
        DataClassReadFromDirectoryCompletedSuccessfullyEvent(data_class=data_class)
    )
    return definitions


def read_files_from_local_directory(
    data_class: type[NldNamedBaseModel] | type[NldBaseModel],
    root_path: str,
) -> dict[str, Any]:
    """
    Read NldBaseModel objects from Jinja template files.

    Args:
        data_class: NldBaseModel or NldNamedBaseModel class type
        root_path: Directory to search for Jinja template files

    Returns:
        Dictionary mapping entity names to instances
    """
    definitions: dict[str, Any] = {}

    log_event_default(
        DataClassReadFromDirectoryStartEvent(data_class=data_class, root_path=root_path)
    )

    is_named = issubclass(data_class, NldNamedBaseModel)

    for file_path in file_util.get_list_of_files_in_cur_folder(
        root_path, JINJA2_FILE_STANDARD_REGEX
    ):
        try:
            file_dict = load_file_into_dict(file_path)
            key, content = next(iter(file_dict.items()))

            if is_named:
                init_dict = {"name": key, "template": content}
                instance = data_class.from_dict(from_dict=init_dict)
                definitions[instance.name] = instance  # type: ignore[attr-defined]
            else:
                file_base_name = Path(file_path).stem
                init_dict = {"template": content}
                instance = data_class.from_dict(from_dict=init_dict)
                definitions[file_base_name] = instance
        except BaseModelReadException as e:
            log_event_default(
                StandardDebugEvent(
                    msg=f"Error on the {data_class.__name__} file: "
                    f"{os.path.basename(file_path)}"
                )
            )
            raise e

    log_event_default(
        StandardTestEvent(
            msg=f"{data_class.__name__} loaded are: "
            f"{', '.join(list(definitions.keys()))}"
        )
    )
    log_event_default(
        DataClassReadFromDirectoryCompletedSuccessfullyEvent(data_class=data_class)
    )
    return definitions


def read_entities_from_yaml_file_list(
    base_model_type: type[NldBaseModel],
    file_paths: list[str],
) -> dict[str, NldNamedBaseModel | NldBaseModel]:
    """
    Read NldBaseModel objects from a list of YAML files.

    Args:
        base_model_type: NldBaseModel or NldNamedBaseModel class type
        file_paths: List of file paths to load

    Returns:
        Dictionary mapping entity names to instances
    """
    definitions: dict[str, NldNamedBaseModel | NldBaseModel] = {}

    is_named = issubclass(base_model_type, NldNamedBaseModel)

    for file_path in file_paths:
        try:
            entity_dict = load_yaml_file_into_dict(file_path)
            if is_named and "name" not in entity_dict:
                entity_dict["name"] = Path(file_path).stem

            resolved_type = _resolve_entity_class(
                base_model_type,
                entity_dict=entity_dict,
            )
            definition = resolved_type.from_dict(
                from_dict=entity_dict,
            )

            if is_named:
                key = definition.name  # type: ignore[attr-defined]
            else:
                key = Path(file_path).stem

            definitions.update({key: definition})
        except BaseModelReadException as e:
            file_name = os.path.basename(file_path)
            log_event_default(
                StandardDebugEvent(
                    msg=f"Error on the {base_model_type.__name__} file: {file_name}"
                )
            )
            raise e

    return definitions


def read_files_from_file_list(
    data_class: type[NldNamedBaseModel] | type[NldBaseModel],
    file_paths: list[str],
) -> dict[str, Any]:
    """
    Read NldBaseModel objects from a list of Jinja template files.

    Args:
        data_class: NldBaseModel or NldNamedBaseModel class type
        file_paths: List of file paths to load

    Returns:
        Dictionary mapping entity names to instances
    """
    definitions: dict[str, Any] = {}

    is_named = issubclass(data_class, NldNamedBaseModel)

    for file_path in file_paths:
        try:
            file_dict = load_file_into_dict(file_path)
            key, content = next(iter(file_dict.items()))

            if is_named:
                init_dict = {"name": key, "template": content}
                instance = data_class.from_dict(from_dict=init_dict)
                definitions[instance.name] = instance  # type: ignore[attr-defined]
            else:
                file_base_name = Path(file_path).stem
                init_dict = {"template": content}
                instance = data_class.from_dict(from_dict=init_dict)
                definitions[file_base_name] = instance
        except BaseModelReadException as e:
            log_event_default(
                StandardDebugEvent(
                    msg=f"Error on the {data_class.__name__} file: "
                    f"{os.path.basename(file_path)}"
                )
            )
            raise e

    return definitions
