import json
import types
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Union, cast, get_args, get_origin

from nld.connector.bigquery.bigquery_data_type import BigQueryDataTypes
from nld.pydantic import BasePydanticStructureMapper, NldBaseModel
from nld.structure import (
    Field,
    FieldCharacterisationDefinitionNames,
    Structure,
    StructureCharacterisation,
    StructureCharacterisationDefinitionNames,
)


class BigQueryPydanticStructureMapper(BasePydanticStructureMapper):
    """Maps Pydantic objects to structures and field types for BigQuery."""

    @staticmethod
    def map_pydantic_type_to_target(python_type: Any) -> str:
        """Map a Pydantic field type to a BigQuery data type."""
        origin = get_origin(python_type)

        if origin is type(None) or origin is None:
            if python_type is type(None):
                return BigQueryDataTypes.STRING
            if hasattr(python_type, "__origin__"):
                origin = python_type.__origin__

        if origin is Union or isinstance(python_type, types.UnionType):
            args = get_args(python_type)
            non_none_types = [arg for arg in args if arg is not type(None)]
            if len(non_none_types) == 1 and len(args) > 1:
                python_type = non_none_types[0]
                origin = get_origin(python_type)
            elif len(non_none_types) > 1:
                return BigQueryDataTypes.STRING

        if origin is list:
            return BigQueryDataTypes.STRING

        if origin is dict:
            return BigQueryDataTypes.STRING

        if python_type is int:
            return BigQueryDataTypes.INT64
        elif python_type is float:
            return BigQueryDataTypes.FLOAT64
        elif python_type is bool:
            return BigQueryDataTypes.BOOL
        elif python_type is str:
            return BigQueryDataTypes.STRING
        elif python_type is datetime:
            # ``TIMESTAMPTZ`` is the sqlglot-canonical name for a
            # timezone-aware timestamp; sqlglot's bigquery dialect
            # renders it as ``TIMESTAMP`` (BigQuery's TZ-aware type).
            # Plain ``TIMESTAMP`` would be rendered as BigQuery
            # ``DATETIME`` (no timezone), which mismatches Python
            # ``datetime.datetime`` values on insert.
            return "TIMESTAMPTZ"
        elif python_type == date:
            return BigQueryDataTypes.DATE
        elif python_type is Decimal:
            return BigQueryDataTypes.NUMERIC

        if isinstance(python_type, type):
            if issubclass(python_type, Enum):
                return BigQueryDataTypes.STRING
            elif issubclass(python_type, NldBaseModel):
                return BigQueryDataTypes.STRING

        return BigQueryDataTypes.STRING

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
                    characterisation=StructureCharacterisationDefinitionNames.PRIMARY_KEY,
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
                                characterisation=StructureCharacterisationDefinitionNames.FUNCTIONAL_KEY,
                                name=name,
                                linked_fields=linked_fields,
                            )
                        )

        return structure

    @classmethod
    def get_field_definitions(
        cls,
        model_class: type[NldBaseModel],
    ) -> dict[str, "Field"]:
        """Extract field definitions from a Pydantic model for BigQuery."""
        fields = {}
        for field_name, field_info in model_class.model_fields.items():
            python_type = field_info.annotation
            bq_type = cls.map_pydantic_type_to_target(python_type)
            is_nullable = cls.is_nullable(python_type)
            field = Field(
                name=field_name,
                data_type=bq_type,
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
        """Handle non-serializable types for json.dumps."""
        if isinstance(obj, datetime | date):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return str(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    @staticmethod
    def prepare_value_for_target(value: Any) -> Any:
        """Prepare a Python value for insertion into BigQuery."""
        if value is None:
            return None
        elif isinstance(value, NldBaseModel):
            return value.model_dump_json()
        elif isinstance(value, Enum):
            return value.value
        elif isinstance(value, list | dict):
            return json.dumps(
                value,
                default=BigQueryPydanticStructureMapper._json_default,
            )
        elif isinstance(value, datetime | date):
            return value
        else:
            return value
