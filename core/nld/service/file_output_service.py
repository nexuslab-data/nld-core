import importlib.resources as resources
import json
import os
import shutil
from types import ModuleType
from typing import Any

from nld.pydantic import NldNamedBaseModel, NldNamespace
from nld.utils.datetime_util import (
    get_current_datetime_as_filesystem_friendly_str,
)
from nld.utils.mixin import NldMixIn
from nld.utils.yaml_util import dump_dict_to_yaml


class FileOutputService(NldMixIn):
    """Service for writing files to a structured output folder.

    The output folder is resolved as follows:
    - If `override_output_folder_path` is provided, it is used as-is.
    - Otherwise, a timestamped folder is created under `output/`
      (e.g. `output/20260227_143000`).

    Individual write methods may append sub-folders to this base path
    (e.g. `internal_folder_name` and `namespace` in `write_yaml_file`).
    """

    def __init__(
        self,
        root_folder_path: str,
        override_output_folder_path: str | None = None,
    ) -> None:
        super().__init__()
        self.root_folder_path = root_folder_path
        self.override_output_folder_path = override_output_folder_path

    def determine_output_folder_path(self) -> str:
        folder_path = (
            self.override_output_folder_path
            if self.override_output_folder_path is not None
            else os.path.join(
                "output", get_current_datetime_as_filesystem_friendly_str()
            )
        )
        return folder_path

    def write_yaml_file(
        self,
        nld_base_model: NldNamedBaseModel,
        internal_folder_name: str | None = None,
        namespace: str | None = None,
    ) -> None:
        output_folder_path = self.determine_output_folder_path()
        if internal_folder_name is not None:
            output_folder_path = os.path.join(output_folder_path, internal_folder_name)
        if namespace is not None:
            namespace_path = NldNamespace(namespace).to_path()
            if namespace_path:
                output_folder_path = os.path.join(output_folder_path, namespace_path)
        os.makedirs(output_folder_path, exist_ok=True)
        nld_data_class_dict = nld_base_model.to_dict()
        nld_data_class_yaml_path = os.path.join(
            output_folder_path, f"{nld_base_model.name}.yml"
        )
        dump_dict_to_yaml(nld_data_class_dict, nld_data_class_yaml_path)

    def resolve_output_file_path(
        self,
        file_name: str,
        internal_folder_name: str | None = None,
        namespace: str | None = None,
    ) -> str:
        """Build the full output file path including subfolders."""
        output_folder_path = self.determine_output_folder_path()
        if internal_folder_name is not None:
            output_folder_path = os.path.join(output_folder_path, internal_folder_name)
        if namespace is not None:
            namespace_path = NldNamespace(namespace).to_path()
            if namespace_path:
                output_folder_path = os.path.join(output_folder_path, namespace_path)
        return os.path.join(output_folder_path, file_name)

    def write_file(
        self,
        file_name: str,
        content: str,
        internal_folder_name: str | None = None,
        namespace: str | None = None,
    ) -> None:
        output_file_path = self.resolve_output_file_path(
            file_name=file_name,
            internal_folder_name=internal_folder_name,
            namespace=namespace,
        )
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        with open(output_file_path, "w") as output_file:
            output_file.write(content)

    def write_json_file(
        self,
        file_name: str,
        data: dict[str, Any] | list[Any],
        indent: int = 2,
    ) -> None:
        """Write a dictionary or list as a JSON file to the output folder."""
        output_folder_path = self.determine_output_folder_path()
        os.makedirs(output_folder_path, exist_ok=True)
        output_file_path = os.path.join(output_folder_path, file_name)
        with open(output_file_path, "w") as output_file:
            json.dump(
                data,
                output_file,
                indent=indent,
            )

    def copy_package_data(
        self,
        package_name: str | ModuleType,
        resource_name: str,
        fail_on_existing_output_folder: bool = False,
    ) -> None:
        output_folder_path = self.determine_output_folder_path()
        if fail_on_existing_output_folder:
            if os.path.exists(output_folder_path):
                raise RuntimeError(
                    f"[✖] Output folder {output_folder_path} already exists."
                )
        try:
            with resources.path(package_name, resource_name) as source_path:
                if not source_path.exists():
                    raise RuntimeError(
                        f"[✖] No resource '{resource_name}' in package "
                        f"'{package_name}' found."
                    )

                shutil.copytree(source_path, output_folder_path, dirs_exist_ok=False)
                self.log_info(
                    f"[✔] Copy of package data for resource {resource_name} "
                    f"to {output_folder_path} - Success"
                )

        except FileNotFoundError as e:
            raise RuntimeError(
                f"[✖] No resource '{resource_name}' in package '{package_name}' exists."
            ) from e
