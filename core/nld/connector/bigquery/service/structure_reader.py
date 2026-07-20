from __future__ import annotations

from typing import Any

from nld.connector.base import QueryWrapper, SQLConnectorStructureReader
from nld.connector.base.structure_reader import (
    escape_sql_literal,
    normalize_structure_type,
    parse_view_dependencies,
)
from nld.connector.bigquery.bigquery_connector import BigQueryConnector
from nld.connector.bigquery.bigquery_structure import BigQueryStructure
from nld.structure import (
    Field,
    FieldCharacterisationDefinitionNames,
    Structure,
    StructureCharacterisation,
)


class BigQueryStructureReader(SQLConnectorStructureReader[BigQueryConnector]):
    """Service to extract database structure from BigQuery.

    Queries INFORMATION_SCHEMA to extract metadata about tables,
    views, and columns within a BigQuery dataset.

    Example:
        >>> reader = BigQueryStructureReader(connector)
        >>> structures = reader.extract_structures(schema="my_dataset")
        >>> for structure in structures:
        ...     print(structure.name, structure.structure_type)
    """

    @property
    def active_database(self) -> str | None:
        """Get the active project ID from the connection."""
        return self._connector.get_active_project()

    def extract_structures(
        self,
        database: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
        **kwargs: Any,
    ) -> list[Structure]:
        """Extract structures (tables/views) from BigQuery.

        In BigQuery terminology:
        - database maps to project
        - schema maps to dataset

        Args:
            database: Optional project ID. Uses active project if None.
            schema: Optional dataset ID to filter by.
            object_name: Optional table/view name to filter by.

        Returns:
            List of Structure objects representing tables and views.
        """
        project = database or self.active_database
        dataset = schema or self._connector.get_active_dataset()

        if dataset is None:
            raise ValueError(
                "A dataset must be specified either via the schema "
                "parameter or in the connection credentials."
            )

        tables = self._get_tables_and_views(
            project=project,
            dataset=dataset,
            object_name=object_name,
        )

        if not tables:
            return []

        table_names = [table["table_name"] for table in tables]
        all_columns = self._get_all_columns(
            project=project,
            dataset=dataset,
            table_names=table_names,
        )

        structures: list[Structure] = []
        for table_info in tables:
            table_name = table_info["table_name"]
            columns = all_columns.get(table_name, [])

            structure = self._build_structure(
                project=project,
                dataset=dataset,
                table_info=table_info,
                columns=columns,
            )
            structures.append(structure)

        return structures

    def get_all_dependent_views(
        self,
        schema: str,
    ) -> dict[str, list[str]]:
        """Return every direct view-dependency edge, parsed from definitions.

        BigQuery has no queryable view-dependency catalog, so the
        edges are derived by parsing INFORMATION_SCHEMA.VIEWS
        definitions.
        """
        project = self.active_database
        project_prefix = f"`{escape_sql_literal(project)}`." if project else ""
        query = (
            "SELECT table_name, view_definition FROM "
            f"{project_prefix}`{escape_sql_literal(schema)}`"
            ".INFORMATION_SCHEMA.VIEWS"
        )
        result = self._connector.execute_query(query)
        result.raise_on_error(f"BigQuery view listing failed: {query}")
        df = result.get_result_df()
        if df.empty:
            return {}
        view_definitions = {
            str(row["table_name"]).lower(): str(row["view_definition"])
            for _, row in df.iterrows()
            if row.get("view_definition")
        }
        return parse_view_dependencies(
            view_definitions=view_definitions,
            dialect="bigquery",
        )

    def _get_tables_and_views(
        self,
        project: str | None,
        dataset: str,
        object_name: str | None,
    ) -> list[dict[str, Any]]:
        """Retrieve the list of tables and views from the dataset."""
        safe_dataset = escape_sql_literal(dataset)
        project_prefix = f"`{escape_sql_literal(project)}`." if project else ""

        # ``object_name`` is interpolated into a SQL string literal, so
        # it MUST be escaped with ``_escape_sql_literal`` (doubling any
        # single quote) — not passed through Jinja unescaped, which
        # would let a value containing ``'`` break out of the literal.
        where_clause = ""
        if object_name:
            safe_object_name = escape_sql_literal(object_name)
            where_clause = f"WHERE table_name = '{safe_object_name}'"

        query = f"""
            SELECT table_name, table_type
            FROM {project_prefix}`{safe_dataset}`.INFORMATION_SCHEMA.TABLES
            {where_clause}
            ORDER BY table_name
        """

        result = self._connector.execute_query(QueryWrapper(query=query))
        df = result.get_result_df()
        if df.empty:
            return []
        return df.to_dict("records")  # type: ignore[return-value]

    def _get_all_columns(
        self,
        project: str | None,
        dataset: str,
        table_names: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Retrieve columns for all specified tables at once."""
        if not table_names:
            return {}

        safe_dataset = escape_sql_literal(dataset)
        project_prefix = f"`{escape_sql_literal(project)}`." if project else ""

        table_filter = ", ".join(
            f"'{escape_sql_literal(name)}'" for name in table_names
        )

        # BigQuery's ``INFORMATION_SCHEMA.COLUMNS`` does not expose
        # ``character_maximum_length``, ``numeric_precision`` or
        # ``numeric_scale`` (those columns belong to ANSI/Postgres /
        # Snowflake). BigQuery types that need a length / precision
        # (NUMERIC(p,s), STRING(n), …) carry that information inline
        # in ``data_type`` instead, so we extract it from there in
        # ``_build_field``.
        query = f"""
            SELECT
                table_name,
                column_name,
                data_type,
                is_nullable
            FROM {project_prefix}`{safe_dataset}`.INFORMATION_SCHEMA.COLUMNS
            WHERE table_name IN ({table_filter})
            ORDER BY table_name, ordinal_position
        """

        result = self._connector.execute_query(QueryWrapper(query=query))
        df = result.get_result_df()

        columns_by_table: dict[str, list[dict[str, Any]]] = {}
        rows: list[dict[str, Any]] = df.to_dict("records")  # type: ignore[assignment]
        for row in rows:
            key = row["table_name"]
            if key not in columns_by_table:
                columns_by_table[key] = []
            columns_by_table[key].append(row)

        return columns_by_table

    def _build_structure(
        self,
        project: str | None,
        dataset: str,
        table_info: dict[str, Any],
        columns: list[dict[str, Any]],
    ) -> BigQueryStructure:
        """Build a Structure object from extracted metadata."""
        table_name = table_info["table_name"]
        table_type = normalize_structure_type(table_info["table_type"])

        fields: dict[str, Field] = {}
        for col in columns:
            field = self._build_field(col)
            fields[field.name] = field

        characterisations: list[StructureCharacterisation] = []

        return BigQueryStructure(
            name=table_name,
            structure_type=table_type,
            connector_type="bigquery",
            properties={
                "project_id": project or "",
                "dataset_id": dataset,
            },
            fields=fields,
            characterisations=characterisations,
        )

    def _build_field(self, column_info: dict[str, Any]) -> Field:
        """Build a Field object from column metadata.

        BigQuery encodes length / precision inside the ``data_type``
        string itself (e.g. ``NUMERIC(10, 2)`` or ``STRING(64)``)
        rather than exposing them as separate INFORMATION_SCHEMA
        columns. We parse the suffix here so the resulting Field
        carries the same length / precision contract as the other
        connectors.
        """
        column_name = column_info["column_name"]
        raw_data_type = column_info["data_type"].upper()
        is_nullable = column_info["is_nullable"]

        data_type, length, precision = self._parse_bq_data_type(raw_data_type)

        field = Field(
            name=column_name,
            data_type=data_type,
            length=length,
            precision=precision,
        )

        if is_nullable == "NO":
            field.add_characterisation(
                FieldCharacterisationDefinitionNames.MANDATORY,
            )

        return field

    @staticmethod
    def _parse_bq_data_type(raw_data_type: str) -> tuple[str, int, int]:
        """Split a BigQuery data type into base type, length, precision.

        Examples:
            ``STRING`` -> ``("STRING", 0, 0)``
            ``NUMERIC(10, 2)`` -> ``("NUMERIC", 10, 2)``
            ``BIGNUMERIC(38, 9)`` -> ``("BIGNUMERIC", 38, 9)``
        """
        if "(" not in raw_data_type or not raw_data_type.endswith(")"):
            return raw_data_type, 0, 0

        base, _, rest = raw_data_type.partition("(")
        inner = rest[:-1]
        parts = [p.strip() for p in inner.split(",")]
        try:
            length = int(parts[0])
        except (ValueError, IndexError):
            return base, 0, 0
        precision = 0
        if len(parts) > 1:
            try:
                precision = int(parts[1])
            except ValueError:
                precision = 0
        return base, length, precision
