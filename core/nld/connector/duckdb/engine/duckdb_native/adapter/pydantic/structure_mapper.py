import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast, get_args, get_origin

from nld.connector.duckdb.connector_definition import DuckDBDataTypes
from nld.pydantic import BasePydanticStructureMapper, NldBaseModel
from nld.structure import (
    Field,
    FieldCharacterisationDefinitionNames,
    Structure,
    StructureCharacterisation,
    StructureCharacterisationDefinitionNames,
)


class DuckDBPydanticStructureMapper(BasePydanticStructureMapper):
    """Maps Pydantic objects to structures and field types for DuckDB."""

    @staticmethod
    def map_pydantic_type_to_target(python_type: Any) -> str:
        """Map a Pydantic field type to a DuckDB data type."""
        # Step 1: unwrap Optional (Union with None) to get the inner type
        python_type = DuckDBPydanticStructureMapper._unwrap_optional(
            python_type,
        )

        # Step 2: resolve the concrete type
        return DuckDBPydanticStructureMapper._resolve_type(python_type)

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
        """Map a resolved Python type to a DuckDB data type."""
        from uuid import UUID

        origin = get_origin(python_type)

        if python_type is type(None):
            return DuckDBDataTypes.VARCHAR

        # Collection types (including bare list/dict without params)
        if origin is list or python_type is list:
            return DuckDBDataTypes.JSON
        if origin is dict or python_type is dict:
            return DuckDBDataTypes.JSON

        # Scalar types
        if python_type is int:
            return DuckDBDataTypes.BIGINT
        if python_type is float:
            return DuckDBDataTypes.DOUBLE
        if python_type is bool:
            return DuckDBDataTypes.BOOLEAN
        if python_type is str:
            return DuckDBDataTypes.VARCHAR
        if python_type is Decimal:
            return DuckDBDataTypes.DECIMAL
        if python_type is datetime:
            return DuckDBDataTypes.TIMESTAMPTZ
        if python_type is date:
            return DuckDBDataTypes.DATE
        if python_type is UUID:
            return DuckDBDataTypes.UUID

        # Class-based types
        if isinstance(python_type, type):
            if issubclass(python_type, Enum):
                return DuckDBDataTypes.VARCHAR
            if issubclass(python_type, NldBaseModel):
                return DuckDBDataTypes.JSON

        return DuckDBDataTypes.VARCHAR

    @classmethod
    def get_structure(cls, model_class: type[NldBaseModel]) -> Structure:
        structure = Structure(
            name=model_class.__name__,
            structure_type="TABLE",
            fields=cls.get_field_definitions(model_class),
        )

        primary_key_fields = []
        for field_name, field_info in model_class.model_fields.items():
            json_schema_extra = field_info.json_schema_extra
            if isinstance(json_schema_extra, dict):
                if json_schema_extra.get("primary_key") is True:
                    primary_key_fields.append(field_name)

        if len(primary_key_fields) > 0:
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
        if model_config:
            json_schema_extra = None
            if isinstance(model_config, dict):
                json_schema_extra = model_config.get("json_schema_extra")
            elif hasattr(model_config, "get"):
                json_schema_extra = model_config.get("json_schema_extra")

            if isinstance(json_schema_extra, dict):
                functional_key = json_schema_extra.get("functional_key")
                if isinstance(functional_key, dict):
                    fields = cast(list[str], functional_key.get("fields", []))
                    name = cast(
                        str,
                        functional_key.get("name", f"FUK_{model_class.__name__}"),
                    )
                    if fields:
                        linked_fields: list[str] = [str(f) for f in fields]
                        structure.add_characterisation(
                            StructureCharacterisation(
                                characterisation=(
                                    StructureCharacterisationDefinitionNames.FUNCTIONAL_KEY
                                ),
                                name=name,
                                linked_fields=linked_fields,
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
            duckdb_type = cls.map_pydantic_type_to_target(python_type)
            is_nullable = cls.is_nullable(python_type)
            field = Field(
                name=field_name,
                data_type=duckdb_type,
                description=field_info.description,
            )
            if not is_nullable:
                field.add_characterisation(
                    FieldCharacterisationDefinitionNames.MANDATORY
                )
            fields[field_name] = field
        return fields

    @staticmethod
    def _json_default(obj: Any) -> Any:
        """Handle non-serializable types for json.dumps.

        Extends the PostgreSQL version with Enum, UUID, and
        NldBaseModel support because DuckDB stores these as JSON
        strings when they appear inside list/dict fields.
        """
        from uuid import UUID

        if isinstance(obj, datetime | date):
            return obj.isoformat()
        if isinstance(obj, Decimal | UUID):
            return str(obj)
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, NldBaseModel):
            return obj.model_dump()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    @staticmethod
    def prepare_value_for_target(value: Any) -> Any:
        """Prepare a Python value for insertion into DuckDB."""
        if value is None:
            return None
        elif isinstance(value, NldBaseModel):
            return value.model_dump_json()
        elif isinstance(value, Enum):
            return value.value
        elif isinstance(value, list | dict):
            return json.dumps(
                value,
                default=DuckDBPydanticStructureMapper._json_default,
            )
        elif isinstance(value, datetime | date):
            return value
        else:
            from uuid import UUID

            # DuckDB's Python driver does not accept raw UUID objects
            # in parameterised queries.  Convert to str so that
            # sqlglot's literal_value can render it correctly.
            # (PostgreSQL's psycopg2 handles UUID natively.)
            if isinstance(value, UUID):
                return str(value)
            return value
