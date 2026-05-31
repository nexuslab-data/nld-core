from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, get_args, get_origin

import pyarrow as pa

from nld.pydantic import BasePydanticStructureMapper, NldBaseModel
from nld.structure import Field, FieldCharacterisationDefinitionNames

from .utils import get_canonical_type_string


class PyArrowPydanticStructureMapper(BasePydanticStructureMapper):
    """
    Maps Pydantic objects to structures and field types for PyArrow.

    This class provides utilities to convert Pydantic model schemas to PyArrow
    schemas by mapping Python type annotations to appropriate PyArrow data types.
    """

    @staticmethod
    def map_pydantic_type_to_target(python_type: Any) -> pa.DataType:
        """
        Map a Pydantic field type to a PyArrow data type.

        Handles various Python types including primitives, Optional types,
        collections, Pydantic models, and enums.

        Args:
            python_type: Python type annotation from Pydantic field

        Returns:
            PyArrow data type

        Example:
            >>> PyArrowPydanticStructureMapper.map_pydantic_type_to_target(int)
            DataType(int64)
        """
        origin = get_origin(python_type)

        # Handle None type
        if origin is type(None) or origin is None:
            if python_type is type(None):
                return pa.string()
            if hasattr(python_type, "__origin__"):
                origin = python_type.__origin__

        # Handle Optional types (Union with None) - unwrap to get inner type
        if hasattr(python_type, "__args__"):
            args = get_args(python_type)
            non_none_types = [arg for arg in args if arg is not type(None)]
            if len(non_none_types) == 1 and len(args) > 1:
                # This is Optional[T] (Union[T, None])
                python_type = non_none_types[0]
                origin = get_origin(python_type)
            elif len(non_none_types) > 1:
                # Union of multiple types - store as string/JSON
                return pa.string()

        # Handle list types
        if origin is list:
            return pa.string()  # Store as JSON string

        # Handle dict types
        if origin is dict:
            return pa.string()  # Store as JSON string

        # Handle primitive types
        if python_type is int:
            return pa.int64()
        elif python_type is float:
            return pa.float64()
        elif python_type is bool:
            return pa.bool_()
        elif python_type is str:
            return pa.string()
        elif python_type is datetime:
            return pa.timestamp("us", tz="UTC")
        elif python_type is date:
            return pa.date32()
        elif python_type is Decimal:
            return pa.string()  # Store Decimal as string for precision

        # Handle UUID
        from uuid import UUID

        if python_type is UUID:
            return pa.string()

        # Handle class types
        if isinstance(python_type, type):
            if issubclass(python_type, Enum):
                return pa.string()
            elif issubclass(python_type, NldBaseModel):
                return pa.string()  # Store nested models as JSON

        # Default to string for unknown types
        return pa.string()

    @classmethod
    def get_field_definitions(cls, model_class: type[NldBaseModel]) -> dict[str, Field]:
        """
        Extract field definitions from a Pydantic model.

        Analyzes all fields in the Pydantic model and generates a mapping of
        field names to Field objects with PyArrow-compatible data types.

        Args:
            model_class: Pydantic model class

        Returns:
            Dictionary mapping field names to Field objects
        """
        fields = {}
        for field_name, field_info in model_class.model_fields.items():
            python_type = field_info.annotation
            pa_type = cls.map_pydantic_type_to_target(python_type)
            is_nullable = cls.is_nullable(python_type)
            field = Field(
                name=field_name,
                data_type=get_canonical_type_string(pa_type),
                description=field_info.description,
            )
            # Mark field as mandatory if not nullable
            if not is_nullable:
                field.add_characterisation(
                    FieldCharacterisationDefinitionNames.MANDATORY
                )
            fields[field_name] = field
        return fields

    @staticmethod
    def prepare_value_for_target(value: Any) -> Any:
        """
        Prepare a Python value for storage in PyArrow/Parquet.

        Converts special types like Pydantic models, enums, Decimals, and
        complex objects to PyArrow-compatible formats.

        Args:
            value: Python value to prepare

        Returns:
            PyArrow-compatible value
        """
        import json

        if value is None:
            return None
        elif isinstance(value, NldBaseModel):
            return value.model_dump_json()
        elif isinstance(value, Enum):
            return value.value
        elif isinstance(value, Decimal):
            return str(value)
        elif isinstance(value, list | dict):
            return json.dumps(value)
        elif isinstance(value, datetime | date):
            return value
        else:
            return value

    @classmethod
    def get_pyarrow_schema(cls, model_class: type[NldBaseModel]) -> pa.Schema:
        """
        Generate a PyArrow schema from a Pydantic model class.

        Args:
            model_class: Pydantic model class

        Returns:
            PyArrow schema with correct nullable settings
        """
        fields = []
        for field_name, field_info in model_class.model_fields.items():
            python_type = field_info.annotation
            pa_type = cls.map_pydantic_type_to_target(python_type)
            is_nullable = cls.is_nullable(python_type)
            fields.append(pa.field(field_name, pa_type, nullable=is_nullable))
        return pa.schema(fields)
