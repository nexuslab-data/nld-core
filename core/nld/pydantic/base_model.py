import copy
import logging
from pathlib import Path
from types import UnionType
from typing import (
    Any,
    Self,
    Union,
    cast,
    get_args,
    get_origin,
)

import yaml

from nld.exceptions import BaseModelDeepCopyException
from nld.logging import BaseEvent, EventLevel, NldLogger
from pydantic import BaseModel, PrivateAttr


class NldBaseModel(BaseModel):
    """
    Extended Pydantic BaseModel with JSON and YAML read/write capabilities.

    Provides independent methods for reading and writing data in both JSON
    and YAML formats.
    """

    _logger: NldLogger | None = PrivateAttr(default=None)
    _resolved_references: dict[str, Any] = PrivateAttr(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Initialize logger after model creation."""
        self._init_logger()

    def _init_logger(self) -> None:
        """Initialize the logger for this instance."""
        self._logger = cast(
            NldLogger,
            logging.getLogger(self.__class__.__name__),
        )

    @property
    def logger(self) -> NldLogger:
        """Get the logger instance."""
        if self._logger is None:
            self._init_logger()
        assert self._logger is not None
        return self._logger

    def log_event(self, event: BaseEvent) -> None:
        """Log an event using the instance logger."""
        self.logger.log_event(event)

    def log_debug(self, message: str) -> None:
        """Log a debug message."""
        self.logger.log(EventLevel.DEBUG, message)

    def log_info(self, message: str) -> None:
        """Log an info message."""
        self.logger.log(EventLevel.INFO, message)

    def log_warn(self, message: str) -> None:
        """Log a warning message."""
        self.logger.log(EventLevel.WARN, message)

    def log_error(self, message: str) -> None:
        """Log an error message."""
        self.logger.log(EventLevel.ERROR, message)

    @classmethod
    def deep_copy(cls, instance: Self) -> Self:
        """
        Create a deep copy of the instance.

        Args:
            instance: Instance to copy

        Returns:
            Deep copy of the instance

        Raises:
            DataClassDeepCopyException: If instance is not of the correct type
        """
        if not isinstance(instance, cls):
            raise BaseModelDeepCopyException(self_object=instance, expected_class=cls)
        return copy.deepcopy(instance)

    @classmethod
    def from_yaml(cls, yaml_content: str) -> Self:
        """
        Read model instance from YAML string.

        Args:
            yaml_content: YAML content as string

        Returns:
            Instance of the model populated with data from the YAML string

        Example:
            >>> yaml_str = "name: test\\nvalue: 42"
            >>> config = MyConfig.from_yaml(yaml_str)
        """
        data = yaml.safe_load(yaml_content)
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls, from_dict: dict[str, Any]) -> Self:
        """
        Read model instance from dictionary.

        Args:
            from_dict: Dictionary with model data

        Returns:
            Instance of the model populated with data from the dictionary

        Example:
            >>> data_dict = {"name": "test", "value": 42}
            >>> config = MyConfig.from_dict(data_dict)
        """
        return cls.model_validate(from_dict)

    def to_dict(
        self,
        exclude_none: bool = True,
        exclude_unset: bool = True,
        exclude_defaults: bool = True,
        preserve_references: bool = True,
    ) -> dict[str, Any]:
        """
        Convert model to a clean dictionary for serialization.

        When a field is dict[str, NldNamedBaseModel], the name key is
        stripped from each value since the dict key already serves as
        the identifier.

        Args:
            exclude_none: Exclude fields with None values.
            exclude_unset: Exclude fields that were not explicitly set.
            exclude_defaults: Exclude fields equal to their default value.
            preserve_references: Restore original string references for fields
                that were resolved from string references during deserialization.

        Example:
            >>> structure = Structure(name="users", ...)
            >>> data = structure.to_dict()
        """
        data = self.model_dump(
            mode="python",
            exclude_none=exclude_none,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
        )
        self.__class__._remove_redundant_names(
            model_cls=self.__class__,
            data=data,
        )
        if preserve_references and self._resolved_references:
            self._restore_references(data=data)
        return data

    def _restore_references(self, data: dict[str, Any]) -> None:
        """Replace resolved fields with their original reference names.

        Mutates the data dict in-place, restoring string references for
        fields that were originally loaded as string references.

        Args:
            data: Serialized dictionary to restore references in
        """
        for field_name, ref_info in self._resolved_references.items():
            if field_name not in data:
                continue

            if isinstance(ref_info, str):
                data[field_name] = ref_info
            elif isinstance(ref_info, dict):
                field_data = data[field_name]
                if isinstance(field_data, list):
                    for index, ref_name in ref_info.items():
                        int_index = int(index)
                        if int_index < len(field_data):
                            field_data[int_index] = ref_name
                elif isinstance(field_data, dict):
                    for key, ref_name in ref_info.items():
                        if key in field_data:
                            field_data[key] = ref_name

    @staticmethod
    def _remove_redundant_names(
        model_cls: type["NldBaseModel"],
        data: dict[str, Any],
    ) -> None:
        """Strip name from dict values where the dict key already serves as name."""
        for field_name, field_info in model_cls.model_fields.items():
            if field_name not in data:
                continue

            annotation = field_info.annotation
            unwrapped = NldBaseModel._unwrap_optional(annotation)
            origin = get_origin(unwrapped)
            args = get_args(unwrapped)

            if origin is dict and len(args) == 2:
                value_type = args[1]
                if (
                    isinstance(value_type, type)
                    and issubclass(value_type, NldBaseModel)
                    and "name" in value_type.model_fields
                ):
                    for value_dict in data[field_name].values():
                        if isinstance(value_dict, dict):
                            value_dict.pop("name", None)
                            NldBaseModel._remove_redundant_names(
                                model_cls=value_type,
                                data=value_dict,
                            )
            elif isinstance(unwrapped, type) and issubclass(unwrapped, NldBaseModel):
                if isinstance(data[field_name], dict):
                    NldBaseModel._remove_redundant_names(
                        model_cls=unwrapped,
                        data=data[field_name],
                    )
            elif origin is list and args:
                item_type = args[0]
                if isinstance(item_type, type) and issubclass(item_type, NldBaseModel):
                    for item in data[field_name]:
                        if isinstance(item, dict):
                            NldBaseModel._remove_redundant_names(
                                model_cls=item_type,
                                data=item,
                            )

    @staticmethod
    def _unwrap_optional(annotation: Any) -> Any:
        """Unwrap Optional/Union types to get the core type."""
        origin = get_origin(annotation)
        if origin is Union or isinstance(annotation, UnionType):
            args = get_args(annotation)
            non_none = [arg for arg in args if arg is not type(None)]
            if len(non_none) == 1:
                return non_none[0]
        return annotation

    @classmethod
    def read_json_file(cls, file_path: str | Path) -> Self:
        """
        Read model instance from JSON file.

        Args:
            file_path: Path to JSON file

        Returns:
            Instance of the model populated with data from the JSON file

        Example:
            >>> config = MyConfig.read_json_file("config.json")
            >>> config = MyConfig.read_json_file(Path("config.json"))
        """
        path = Path(file_path)
        with path.open(mode="r", encoding="utf-8") as f:
            data = f.read()
        return cls.model_validate_json(data)

    def write_json_file(
        self,
        file_path: str | Path,
        *,
        indent: int = 2,
        exclude_none: bool = False,
    ) -> None:
        """
        Write model instance to JSON file.

        Args:
            file_path: Path where JSON file will be written
            indent: Number of spaces for indentation
            exclude_none: Whether to exclude fields with None values

        Example:
            >>> config = MyConfig(name="test", value=42)
            >>> config.write_json_file("config.json")
            >>> config.write_json_file(Path("config.json"))
        """
        path = Path(file_path)
        json_str = self.model_dump_json(
            indent=indent,
            exclude_none=exclude_none,
        )
        with path.open(mode="w", encoding="utf-8") as f:
            f.write(json_str)

    def write_yaml_file(
        self,
        file_path: str | Path,
        *,
        exclude_none: bool = False,
        sort_keys: bool = False,
        preserve_references: bool = True,
    ) -> None:
        """
        Write model instance to YAML file.

        Args:
            file_path: Path where YAML file will be written
            exclude_none: Whether to exclude fields with None values
            sort_keys: Whether to sort keys alphabetically
            preserve_references: Restore original string references for fields
                that were resolved from string references during deserialization.

        Example:
            >>> config = MyConfig(name="test", value=42)
            >>> config.write_yaml_file("config.yml")
            >>> config.write_yaml_file(Path("config.yml"))
        """
        path = Path(file_path)
        data: dict[str, Any] = self.model_dump(
            mode="python",
            exclude_none=exclude_none,
        )
        if preserve_references and self._resolved_references:
            self._restore_references(data=data)
        with path.open(mode="w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                sort_keys=sort_keys,
                allow_unicode=True,
            )

    @classmethod
    def get_contained_model_types(cls) -> list[type["NldBaseModel"]]:
        """
        Get all NldBaseModel types contained in this model's fields.

        Returns:
            List of NldBaseModel types referenced by this model's fields

        Example:
            >>> class Inner(NldBaseModel):
            ...     value: int
            >>> class Outer(NldBaseModel):
            ...     inner: Inner
            >>> Outer.get_contained_model_types()
            [<class 'Inner'>]
        """
        contained_types: list[type[NldBaseModel]] = []

        for _field_name, field_info in cls.model_fields.items():
            field_type = field_info.annotation
            if field_type is None:
                continue

            contained_types.extend(
                cls._extract_nld_base_models_from_type(field_type=field_type)
            )

        return list(set(contained_types))

    @classmethod
    def _extract_nld_base_models_from_type(
        cls, field_type: Any
    ) -> list[type["NldBaseModel"]]:
        """
        Extract NldBaseModel types from a field type annotation.

        Args:
            field_type: The type annotation to analyze

        Returns:
            List of NldBaseModel types found in the annotation
        """
        result: list[type[NldBaseModel]] = []

        origin = get_origin(field_type)
        args = get_args(field_type)

        if origin is Union or isinstance(field_type, UnionType):
            for arg in args:
                if arg is not type(None):
                    result.extend(
                        cls._extract_nld_base_models_from_type(field_type=arg)
                    )
        elif origin in (list, list):
            if args:
                result.extend(
                    cls._extract_nld_base_models_from_type(field_type=args[0])
                )
        elif origin in (dict, dict):
            if args and len(args) > 1:
                result.extend(
                    cls._extract_nld_base_models_from_type(field_type=args[1])
                )
        else:
            if isinstance(field_type, type) and issubclass(field_type, NldBaseModel):
                result.append(field_type)

        return result
