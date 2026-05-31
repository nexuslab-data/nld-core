import copy
from typing import Any

from nld.logging import NldLoggable
from nld.task.context.variables import (
    CONFIG_FOLDER_PATH,
    ROOT_FOLDER_PATH,
)


class TaskRequest(NldLoggable):
    """
    Represents a task execution request with parameters and extra arguments.

    Attributes:
        execution_name: Unique name for this execution.
        params: Dictionary of task parameters.
        extra_args: Dictionary of additional command-line arguments parsed
                    from CLI format (--key=value).

    Note:
        When parameters appear in both params and extra_args, params values
        take precedence. A warning is logged when duplicates are detected.
    """

    completion_label: str | None
    execution_name: str
    params: dict[str, Any]
    extra_args: dict[str, Any]

    def __init__(
        self,
        execution_name: str,
        params: dict[str, Any] | None = None,
        extra_args: list[str] | None = None,
        completion_label: str | None = None,
    ):
        """
        Initialize TaskRequest with execution name, parameters, and optional
        extra arguments.

        Args:
            execution_name: Unique identifier for the task execution.
            params: Optional dictionary of task parameters. Defaults to empty
                    dictionary if not provided.
            extra_args: Optional list of CLI-style arguments in the format
                        --key=value. Keys with hyphens are converted to have
                        underscores. Defaults to empty dictionary if not
                        provided.

        Raises:
            RuntimeError: If extra_args contains arguments not in --key=value
                          format.
        """
        super().__init__()

        self.completion_label = completion_label
        self.execution_name = execution_name

        self.params = copy.deepcopy(params) if params is not None else {}

        extra_args_dict = {}
        if extra_args is not None:
            for arg in extra_args:
                # Parse CLI-style arguments in --key=value format.
                if arg.startswith("--") and "=" in arg:
                    key, value = arg[2:].split("=", 1)
                    # Replace hyphens with underscores for Python compatibility.
                    key = key.replace("-", "_")
                    extra_args_dict[key] = value
                else:
                    raise RuntimeError(f"Invalid format (expected key=value): {arg}")
        self.extra_args = extra_args_dict

        # Check for duplicate keys between params and extra_args.
        duplicate_keys = set(self.params.keys()) & set(self.extra_args.keys())
        if duplicate_keys:
            duplicate_list = ", ".join(sorted(duplicate_keys))
            self.log_warn(
                f"Duplicate parameters found in both params and extra_args: "
                f"{duplicate_list}. Values from params will take precedence."
            )

    def get_parameters(self, exclude_extra_args: bool = False) -> dict[str, Any]:
        """
        Get all parameters merging params and extra_args dictionaries.

        Args:
            exclude_extra_args: If True, only return params without merging
                                extra_args. Defaults to False.

        Returns:
            Dictionary containing params merged with extra_args (if not
            excluded). When merged, params take precedence over extra_args
            for duplicate keys.
        """
        if exclude_extra_args:
            return self.params
        return self.extra_args | self.params

    @property
    def nld_root_folder_path(self) -> str | None:
        """
        Get the NLD root folder path from parameters.

        Returns:
            Config folder path if present in parameters, otherwise None.
        """
        root_folder_path = self.get_parameters().get(ROOT_FOLDER_PATH)
        return (
            root_folder_path
            if root_folder_path is not None and root_folder_path != ""
            else None
        )

    @property
    def nld_config_folder_path(self) -> str | None:
        """
        Get the NLD configuration folder path from parameters.

        Returns:
            Config folder path if present in parameters, otherwise None.
        """
        config_folder_path = self.get_parameters().get(CONFIG_FOLDER_PATH)
        return (
            config_folder_path
            if config_folder_path is not None and config_folder_path != ""
            else None
        )
