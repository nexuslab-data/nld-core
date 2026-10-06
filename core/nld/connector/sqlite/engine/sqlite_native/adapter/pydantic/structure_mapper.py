import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast, get_args, get_origin
from uuid import UUID

from nld.connector.sqlite.connector_definition import SQLiteDataTypes
from nld.pydantic import BasePydanticStructureMapper, NldBaseModel
from nld.structure import (
    Field,
    FieldCharacterisationDefinitionNames,
    Structure,
    StructureCharacterisation,
    StructureCharacterisationDefinitionNames,
)


class SQLitePydanticStructureMapper(BasePydanticStructureMapper):
    """Maps Pydantic objects to structures and field types for SQLite."""

    @staticmethod
    def map_pydantic_type_to_target(python_type: Any) -> str:
        """Map a Pydantic field type to a SQLite data type."""
        unwrapped = SQLitePydanticStructureMapper._unwrap_optional(python_type)
        return SQLitePydanticStructureMapper._resolve_type(unwrapped)

    @staticmethod
    def _unwrap_optional(python_type: Any) -> Any:
        """Unwrap Optional[X] / X | None to X."""
        args = get_args(python_type)
        if not args:
            return python_type
        non_none_types = [arg for arg in args if arg is not type(None)]
        if len(non_none_types) == 1 and len(args) > 1:
            return non_none_types[0]
        return python_type

    @staticmethod
    def _resolve_type(python_type: Any) -> str:
        """Map a resolved Python type to a SQLite data type."""
        origin = get_origin(python_type)

        if python_type is type(None):
            return SQLiteDataTypes.TEXT

        # Collections are stored as JSON text.
        if origin is list or python_type is list:
            return SQLiteDataTypes.JSON
        if origin is dict or python_type is dict:
            return SQLiteDataTypes.JSON

        # bool must be tested before int: bool is a subclass of int.
        if python_type is bool:
            return SQLiteDataTypes.BOOLEAN
        if python_type is int:
            return SQLiteDataTypes.INTEGER
        if python_type is float:
            return SQLiteDataTypes.REAL
        if python_type is str:
            return SQLiteDataTypes.TEXT
        if python_type is Decimal:
            return SQLiteDataTypes.NUMERIC
        if python_type is datetime:
            return SQLiteDataTypes.TIMESTAMPTZ
        if python_type is date:
            return SQLiteDataTypes.DATE
        if python_type is UUID:
            return SQLiteDataTypes.UUID
        if python_type is bytes:
            return SQLiteDataTypes.BLOB

        if isinstance(python_type, type):
            if issubclass(python_type, Enum):
                return SQLiteDataTypes.TEXT
            if issubclass(python_type, NldBaseModel):
                return SQLiteDataTypes.JSON

        return SQLiteDataTypes.TEXT

    @classmethod
    def get_structure(cls, model_class: type[NldBaseModel]) -> Structure:
        structure = Structure(
            name=model_class.__name__,
            structure_type="TABLE",
            fields=cls.get_field_definitions(model_class),
        )

        primary_key_fields = [
            field_name
            for field_name, field_info in model_class.model_fields.items()
            if isinstance(field_info.json_schema_extra, dict)
            and field_info.json_schema_extra.get("primary_key") is True
        ]
        if primary_key_fields:
            structure.add_characterisation(
                StructureCharacterisation(
                    characterisation=(
                        StructureCharacterisationDefinitionNames.PRIMARY_KEY
                    ),
                    name=f"PK_{model_class.__name__}",
                    linked_fields=primary_key_fields,
                )
            )

        model_config = getattr(model_class, "model_config", None)
        json_schema_extra = (
            model_config.get("json_schema_extra") if model_config else None
        )
        if isinstance(json_schema_extra, dict):
            functional_key = json_schema_extra.get("functional_key")
            if isinstance(functional_key, dict):
                fields = cast(list[str], functional_key.get("fields", []))
                name = cast(
                    str,
                    functional_key.get("name", f"FUK_{model_class.__name__}"),
                )
                if fields:
                    structure.add_characterisation(
                        StructureCharacterisation(
                            characterisation=(
                                StructureCharacterisationDefinitionNames.FUNCTIONAL_KEY
                            ),
                            name=name,
                            linked_fields=[str(field) for field in fields],
                        )
                    )

        return structure

    @classmethod
    def get_field_definitions(
        cls, model_class: type[NldBaseModel]
    ) -> dict[str, "Field"]:
        """Extract field definitions from a Pydantic model."""
        fields = {}
        for field_name, field_info in model_class.model_fields.items():
            python_type = field_info.annotation
            field = Field(
                name=field_name,
                data_type=cls.map_pydantic_type_to_target(python_type),
                description=field_info.description,
            )
            if not cls.is_nullable(python_type):
                field.add_characterisation(
                    FieldCharacterisationDefinitionNames.MANDATORY
                )
            fields[field_name] = field
        return fields

    @staticmethod
    def _json_default(value: Any) -> Any:
        """Handle non-serializable types for json.dumps."""
        if isinstance(value, datetime | date):
            return value.isoformat()
        if isinstance(value, Decimal | UUID):
            return str(value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, NldBaseModel):
            return value.model_dump()
        raise TypeError(
            f"Object of type {type(value).__name__} is not JSON serializable"
        )

    @staticmethod
    def prepare_value_for_target(value: Any) -> Any:
        """Prepare a Python value for insertion into SQLite.

        SQLite stores five types and none of them is a date, a decimal or a
        structured value, so everything else is written as text: datetimes
        as ISO 8601 in UTC (a naive value is read as UTC), dates as ISO
        8601, decimals as their exact decimal string, and models, lists and
        dicts as JSON. Reading them back through a Pydantic model parses
        each one from that text.

        The exact decimal string only survives in a column whose affinity is
        TEXT. A column declared NUMERIC or DECIMAL has NUMERIC affinity, and
        SQLite converts a numeric-looking string into an INTEGER or a REAL
        on the way in, so trailing zeros are lost: declare the column TEXT
        when the exact digits matter.
        """
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, NldBaseModel):
            return value.model_dump_json()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, list | dict):
            return json.dumps(
                value,
                default=SQLitePydanticStructureMapper._json_default,
            )
        if isinstance(value, datetime):
            aware_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value
            return aware_value.astimezone(UTC).isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal | UUID):
            return str(value)
        return value
