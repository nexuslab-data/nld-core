from __future__ import annotations

import abc
from abc import ABC
from typing import TYPE_CHECKING, Any

from nld.exceptions import NotImplementedMethodException
from nld.pydantic.backend.base_structure_mapper import BasePydanticStructureMapper
from nld.pydantic.base_model import NldBaseModel
from nld.pydantic.field_utils import TS_INSERTED_AT, TS_UPDATED_AT

if TYPE_CHECKING:
    from nld.structure import Structure


class NldBaseModelManager(ABC):
    connector: Any
    structure_mapper: BasePydanticStructureMapper
    """
    Abstract base class for Pydantic model database managers.

    This class defines the interface that all database-specific model managers
    must implement. It provides a consistent API for persisting Pydantic models
    to various database backends.

    Subclasses must implement all methods to provide database-specific
    functionality for operations like insert, update, and upsert.
    """

    _TIMESTAMP_COLUMN_TYPE: str = "TIMESTAMPTZ"
    _TIMESTAMP_DEFAULT: str = "CURRENT_TIMESTAMP"

    def _build_table_structure(
        self,
        model_class: type[NldBaseModel],
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
        timestamp_column_type: str = "TIMESTAMPTZ",
        timestamp_default: str = "CURRENT_TIMESTAMP",
    ) -> tuple[Structure, list[str] | None]:
        """Build a Structure from a model class with common pre-processing.

        Handles field exclusion, timestamp column injection, and primary key
        extraction. Subclasses should call this in their create_table
        implementations instead of duplicating the logic.

        Returns a tuple of (structure, primary_key_fields).
        """
        from nld.structure import (
            Field,
            StructureCharacterisationDefinitionNames,
        )

        structure = self.structure_mapper.get_structure(model_class)

        if exclude_fields:
            existing_excluded = [
                field_name
                for field_name in exclude_fields
                if field_name in structure.fields
            ]
            structure.remove_fields(existing_excluded)

        if track_timestamps:
            structure.add_field(
                Field(
                    name=TS_INSERTED_AT,
                    data_type=timestamp_column_type,
                    default_value=timestamp_default,
                ),
            )
            structure.add_field(
                Field(
                    name=TS_UPDATED_AT,
                    data_type=timestamp_column_type,
                    default_value=timestamp_default,
                ),
            )

        primary_key_fields = None
        pk_char = structure.get_characterisation(
            StructureCharacterisationDefinitionNames.PRIMARY_KEY
        )
        if pk_char:
            primary_key_fields = pk_char.linked_fields

        return structure, primary_key_fields

    def create_table(
        self,
        model_class: type[NldBaseModel],
        schema_name: str,
        table_name: str,
        table_exists: str = "skip",
        use_functional_key_as_primary: bool = False,
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
    ) -> None:
        """Create a table based on Pydantic model structure.

        Handles timestamp column injection, primary key resolution
        (including functional key override), table creation via the
        connector, and optional functional key index creation.

        Subclasses can override ``_TIMESTAMP_COLUMN_TYPE`` and
        ``_TIMESTAMP_DEFAULT`` for dialect-specific defaults and
        ``_create_functional_key_index`` to create indexes after the
        table is created. A table that already existed is left as is: its
        functional key index is not created.
        """
        from nld.structure import StructureCharacterisationDefinitionNames

        structure, _ = self._build_table_structure(
            model_class=model_class,
            exclude_fields=exclude_fields,
            track_timestamps=track_timestamps,
            timestamp_column_type=self._TIMESTAMP_COLUMN_TYPE,
            timestamp_default=self._TIMESTAMP_DEFAULT,
        )

        table_path = f"{schema_name}.{table_name}"
        override_primary_key_fields = None
        if use_functional_key_as_primary:
            functional_key = structure.get_characterisation(
                StructureCharacterisationDefinitionNames.FUNCTIONAL_KEY
            )
            if functional_key:
                override_primary_key_fields = functional_key.linked_fields

        create_result = self.connector.create_table(
            table_path,
            structure,
            table_exists=table_exists,
            override_primary_key_fields=override_primary_key_fields,
        )

        # The index belongs to the table's creation. On a table that already
        # existed, even an IF NOT EXISTS index DDL takes a lock blocking every
        # writer, and backends ensure their tables at every flow start.
        if create_result is None:
            return

        self._create_functional_key_index(
            structure=structure,
            table_name=table_name,
            table_path=table_path,
            use_functional_key_as_primary=use_functional_key_as_primary,
        )

    def _create_functional_key_index(  # noqa: B027
        self,
        structure: Structure,
        table_name: str,
        table_path: str,
        use_functional_key_as_primary: bool,
    ) -> None:
        """Hook for creating functional key indexes after table creation.

        Override in subclasses whose connector supports index creation.
        The default implementation is a no-op.
        """

    @abc.abstractmethod
    def insert_model(
        self,
        model: NldBaseModel,
        schema_name: str,
        table_name: str,
        commit: bool = True,
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
    ) -> None:
        """Insert a Pydantic model instance into a database table or object."""
        raise NotImplementedMethodException(self.__class__, "insert_model")

    @abc.abstractmethod
    def update_model(
        self,
        model: NldBaseModel,
        schema_name: str,
        table_name: str,
        commit: bool = True,
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
    ) -> None:
        """Update a Pydantic model instance based on its primary key."""
        raise NotImplementedMethodException(self.__class__, "update_model")

    @abc.abstractmethod
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
        """Upserts a Pydantic model instance based on its primary key."""
        raise NotImplementedMethodException(self.__class__, "upsert_model")

    @abc.abstractmethod
    def read_model(
        self,
        model_class: type[NldBaseModel],
        schema_name: str,
        table_name: str,
        where_conditions: dict[str, Any] | None = None,
        order_by: list[str] | None = None,
        exclude_fields: set[str] | None = None,
    ) -> NldBaseModel | None:
        """Read a single Pydantic model instance from the database."""
        raise NotImplementedMethodException(self.__class__, "read_model")

    @abc.abstractmethod
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
        """Read multiple Pydantic model instances from the database."""
        raise NotImplementedMethodException(self.__class__, "read_models")

    @abc.abstractmethod
    def _prepare_value(self, value: Any) -> Any:
        """
        Prepare a value for insertion into the database.

        This method should handle conversion of Python types to database-compatible
        formats, such as converting Pydantic models to JSON, enums to strings, etc.

        Args:
            value: Value to prepare

        Returns:
            Database-compatible value

        Raises:
            NotImplementedMethodException: Must be implemented by subclass
        """
        raise NotImplementedMethodException(self.__class__, "_prepare_value")
