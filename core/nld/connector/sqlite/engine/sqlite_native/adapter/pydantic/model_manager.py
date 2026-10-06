from __future__ import annotations

import json
from types import UnionType
from typing import TYPE_CHECKING, Any, Union, get_args, get_origin

from pydantic import BaseModel

from nld.connector.sqlite.constants import SQLITE_DIALECT
from nld.connector.sqlite.engine.sqlite_native.connector import (
    SQLiteSQLConnector,
)
from nld.pydantic import NldBaseModel, NldBaseModelManager
from nld.pydantic.field_utils import TS_INSERTED_AT, TS_UPDATED_AT
from nld.utils.sqlglot import (
    identifier_list,
    literal_value,
    quote_identifier,
)

from .structure_mapper import SQLitePydanticStructureMapper

if TYPE_CHECKING:
    from nld.structure import Structure

# SQLite renders the current instant as UTC text, matching the ISO 8601
# encoding the structure mapper writes for a datetime.
CURRENT_TIMESTAMP_EXPRESSION = "STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')"


def _expects_structured_value(annotation: Any) -> bool:
    """Whether a model field holds a value SQLite can only store as JSON.

    A dict, a list or a nested model is written as JSON text, so the read
    path has to decode it: unlike a datetime, a date or a Decimal, Pydantic
    will not parse those from a string when validating a Python record.
    """
    if annotation is None:
        return False
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return any(_expects_structured_value(arg) for arg in get_args(annotation))
    candidate = origin or annotation
    if not isinstance(candidate, type):
        return False
    if issubclass(candidate, str | bytes):
        return False
    return issubclass(candidate, dict | list | tuple | set | BaseModel)


class NldBaseModelSQLiteManager(NldBaseModelManager):
    """Manages Pydantic model persistence operations on SQLite.

    Provides insert, update, upsert and read operations for Pydantic model
    instances against a SQLite database.

    Note: the ``commit`` parameter accepted by the write methods exists for
    API compatibility with the base class and has no effect. Each operation
    runs in its own transaction through ``execute_query``.
    """

    def __init__(self, connector: SQLiteSQLConnector) -> None:
        self.connector = connector
        self.structure_mapper = SQLitePydanticStructureMapper()

    def _prepare_value(self, value: Any) -> Any:
        return self.structure_mapper.prepare_value_for_target(value)

    def _table_reference(self, table_name: str) -> str:
        """Render the quoted table reference in the single SQLite namespace."""
        return quote_identifier(table_name, dialect=SQLITE_DIALECT)

    def _create_functional_key_index(
        self,
        structure: Structure,
        table_name: str,
        table_path: str,
        use_functional_key_as_primary: bool,
    ) -> None:
        from nld.structure import StructureCharacterisationDefinitionNames

        if use_functional_key_as_primary:
            return

        functional_key = structure.get_characterisation(
            StructureCharacterisationDefinitionNames.FUNCTIONAL_KEY
        )
        if functional_key and functional_key.linked_fields:
            self.connector.create_index(
                index_name=f"{functional_key.name}_{table_name}".lower(),
                table_path=table_path,
                columns=functional_key.linked_fields,
                unique=False,
            )

    def insert_model(
        self,
        model: NldBaseModel,
        schema_name: str,
        table_name: str,
        commit: bool = True,
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
    ) -> None:
        data = model.model_dump(exclude=exclude_fields)
        columns = list(data.keys())
        value_strings = [
            literal_value(
                self._prepare_value(data[column]),
                dialect=SQLITE_DIALECT,
            )
            for column in columns
        ]

        if track_timestamps:
            columns.append(TS_INSERTED_AT)
            value_strings.append(CURRENT_TIMESTAMP_EXPRESSION)
            columns.append(TS_UPDATED_AT)
            value_strings.append(CURRENT_TIMESTAMP_EXPRESSION)

        cols = identifier_list(columns, dialect=SQLITE_DIALECT)
        vals = ", ".join(value_strings)
        self.connector.execute_query(
            f"INSERT INTO {self._table_reference(table_name)} ({cols}) VALUES ({vals})"
        )

    def update_model(
        self,
        model: NldBaseModel,
        schema_name: str,
        table_name: str,
        commit: bool = True,
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
    ) -> None:
        structure = self.structure_mapper.get_structure(model.__class__)
        if not structure.has_primary_key():
            raise ValueError(
                f"The base model {model.__class__.__name__} has no "
                "primary key and thus cannot be updated."
            )
        where_fields = [field.name for field in structure.get_primary_key_fields()]
        data = model.model_dump(exclude=exclude_fields)
        update_fields = [field for field in data.keys() if field not in where_fields]

        if not update_fields:
            raise ValueError("No fields to update after excluding where_fields")

        set_parts = [
            f"{quote_identifier(field, dialect=SQLITE_DIALECT)} = "
            f"{literal_value(self._prepare_value(data[field]), dialect=SQLITE_DIALECT)}"
            for field in update_fields
        ]

        if track_timestamps:
            quoted_timestamp = quote_identifier(
                TS_UPDATED_AT,
                dialect=SQLITE_DIALECT,
            )
            set_parts.append(f"{quoted_timestamp} = {CURRENT_TIMESTAMP_EXPRESSION}")

        dml_builder = self.connector.get_dml_builder()
        where_clause = dml_builder.and_clause(
            [
                dml_builder.equality_clause(
                    field=field,
                    value=self._prepare_value(data[field]),
                )
                for field in where_fields
            ]
        )
        self.connector.execute_query(
            f"UPDATE {self._table_reference(table_name)} "
            f"SET {', '.join(set_parts)} WHERE {where_clause}"
        )

    def upsert_model(
        self,
        model: NldBaseModel,
        schema_name: str,
        table_name: str,
        conflict_fields: list[str] | None = None,
        commit: bool = True,
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
    ) -> None:
        structure = self.structure_mapper.get_structure(model.__class__)

        if conflict_fields is None:
            if not structure.has_primary_key():
                raise ValueError(
                    f"The base model {model.__class__.__name__} has "
                    "no primary key and conflict_fields parameter "
                    "was not provided."
                )
            conflict_fields = [
                field.name for field in structure.get_primary_key_fields()
            ]

        data = model.model_dump(exclude=exclude_fields)
        columns = list(data.keys())
        value_strings = [
            literal_value(
                self._prepare_value(data[column]),
                dialect=SQLITE_DIALECT,
            )
            for column in columns
        ]

        if track_timestamps:
            columns.append(TS_INSERTED_AT)
            value_strings.append(CURRENT_TIMESTAMP_EXPRESSION)
            columns.append(TS_UPDATED_AT)
            value_strings.append(CURRENT_TIMESTAMP_EXPRESSION)

        update_fields = [column for column in columns if column not in conflict_fields]
        if not update_fields:
            raise ValueError(
                "No fields to update in conflict resolution "
                "after excluding conflict_fields"
            )

        timestamp_columns = (
            {TS_INSERTED_AT, TS_UPDATED_AT} if track_timestamps else set()
        )
        update_parts = [
            f"{quote_identifier(field, dialect=SQLITE_DIALECT)} = "
            f"EXCLUDED.{quote_identifier(field, dialect=SQLITE_DIALECT)}"
            for field in update_fields
            if field not in timestamp_columns
        ]
        if track_timestamps:
            quoted_timestamp = quote_identifier(
                TS_UPDATED_AT,
                dialect=SQLITE_DIALECT,
            )
            update_parts.append(f"{quoted_timestamp} = {CURRENT_TIMESTAMP_EXPRESSION}")

        # Change-detection WHERE clause: only update when a data column
        # actually changed, so a no-op upsert does not bump ts_updated_at.
        # SQLite spells the null-safe comparison IS NOT.
        comparable_columns = [
            field for field in update_fields if field not in timestamp_columns
        ]
        change_where = ""
        if comparable_columns:
            conditions = [
                f"{quote_identifier(table_name, dialect=SQLITE_DIALECT)}"
                f".{quote_identifier(column, dialect=SQLITE_DIALECT)}"
                f" IS NOT "
                f"EXCLUDED.{quote_identifier(column, dialect=SQLITE_DIALECT)}"
                for column in comparable_columns
            ]
            change_where = f" WHERE ({' OR '.join(conditions)})"

        cols = identifier_list(columns, dialect=SQLITE_DIALECT)
        vals = ", ".join(value_strings)
        conflict_cols = identifier_list(conflict_fields, dialect=SQLITE_DIALECT)
        self.connector.execute_query(
            f"INSERT INTO {self._table_reference(table_name)} ({cols}) "
            f"VALUES ({vals}) "
            f"ON CONFLICT ({conflict_cols}) DO UPDATE SET "
            f"{', '.join(update_parts)}{change_where}"
        )

    def read_model(
        self,
        model_class: type[NldBaseModel],
        schema_name: str,
        table_name: str,
        where_conditions: dict[str, Any] | None = None,
        order_by: list[str] | None = None,
        exclude_fields: set[str] | None = None,
    ) -> NldBaseModel | None:
        models = self.read_models(
            model_class=model_class,
            schema_name=schema_name,
            table_name=table_name,
            where_conditions=where_conditions,
            limit=1,
            order_by=order_by,
            exclude_fields=exclude_fields,
        )
        return models[0] if models else None

    def read_models(
        self,
        model_class: type[NldBaseModel],
        schema_name: str,
        table_name: str,
        where_conditions: dict[str, Any] | None = None,
        limit: int | None = None,
        order_by: list[str] | None = None,
        exclude_fields: set[str] | None = None,
    ) -> list[NldBaseModel]:
        table_ref = self._table_reference(table_name)

        if exclude_fields:
            selected_columns = [
                field_name
                for field_name in model_class.model_fields
                if field_name not in exclude_fields
            ]
            cols = identifier_list(selected_columns, dialect=SQLITE_DIALECT)
            query_str = f"SELECT {cols} FROM {table_ref}"
        else:
            query_str = f"SELECT * FROM {table_ref}"

        if where_conditions:
            dml_builder = self.connector.get_dml_builder()
            where = dml_builder.and_clause(
                [
                    dml_builder.equality_clause(
                        field=field,
                        value=self._prepare_value(value),
                    )
                    for field, value in where_conditions.items()
                ]
            )
            query_str += f" WHERE {where}"

        if order_by:
            order_parts = []
            for field in order_by:
                if field.startswith("-"):
                    quoted = quote_identifier(field[1:], dialect=SQLITE_DIALECT)
                    order_parts.append(f"{quoted} DESC")
                else:
                    quoted = quote_identifier(field, dialect=SQLITE_DIALECT)
                    order_parts.append(f"{quoted} ASC")
            query_str += f" ORDER BY {', '.join(order_parts)}"

        if limit is not None:
            if not isinstance(limit, int):
                raise TypeError(f"limit must be int, got {type(limit).__name__}")
            query_str += f" LIMIT {literal_value(limit, dialect=SQLITE_DIALECT)}"

        result = self.connector.execute_query(query_str)
        return [
            model_class.model_validate(
                self._restore_record(
                    model_class=model_class,
                    record=record,
                ),
            )
            for record in result.get_result_records()
        ]

    @staticmethod
    def _restore_record(
        model_class: type[NldBaseModel],
        record: dict[str, Any],
    ) -> dict[str, Any]:
        """Decode back the columns written as JSON text.

        ``prepare_value_for_target`` writes a dict, a list or a nested model
        as JSON because SQLite has no structured type. Text that is left as
        it comes back reaches Pydantic as a string and fails validation on
        those fields, so it is parsed here, symmetrically with the write.
        """
        restored = dict(record)
        for field_name, field_info in model_class.model_fields.items():
            value = restored.get(field_name)
            if not isinstance(value, str):
                continue
            if not _expects_structured_value(field_info.annotation):
                continue
            try:
                restored[field_name] = json.loads(value)
            except json.JSONDecodeError:
                # Leave the raw text in place: reporting it as the validation
                # error of its own field says more than a decoding error here.
                continue
        return restored
