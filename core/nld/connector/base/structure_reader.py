from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from nld.structure import Structure

from .connector import DataConnector, SQLDataConnector


def escape_sql_literal(value: str) -> str:
    """Escape a SQL string literal by doubling single quotes.

    Only intended for internal catalog queries where values are
    schema/table names from framework config — never for user-facing
    input.
    """
    return value.replace("'", "''")


def normalize_column_default(raw_default: Any) -> str | None:
    """Normalize a read-back column default for comparison.

    Engines report defaults with a cast suffix (``'open'::VARCHAR``,
    ``0::numeric``); the declared YAML value carries none, so the
    suffix is stripped to compare equal.
    """
    if raw_default is None or (
        not isinstance(raw_default, str) and pd.isna(raw_default)
    ):
        return None
    return str(raw_default).split("::")[0].strip()


def parse_view_dependencies(
    view_definitions: dict[str, str],
    dialect: str,
) -> dict[str, list[str]]:
    """Build direct view-dependency edges by parsing view definitions.

    Maps each referenced object name (lowercased, unqualified) to the
    sorted list of views whose definition references it. Engines
    without a queryable dependency catalog (Snowflake's
    OBJECT_DEPENDENCIES lags by hours; DuckDB and BigQuery have none)
    derive the edges from the definitions themselves. A definition
    sqlglot cannot parse contributes no edges — never an error, since
    an unrelated exotic view must not block a deploy.
    """
    import sqlglot
    from sqlglot import exp

    graph: dict[str, list[str]] = {}
    for view_name, definition in view_definitions.items():
        try:
            parsed = sqlglot.parse_one(definition, dialect=dialect)
        except Exception:
            continue
        sources = {
            table.name.lower()
            for table in parsed.find_all(exp.Table)
            if table.name and table.name.lower() != view_name.lower()
        }
        for source_name in sources:
            graph.setdefault(source_name, []).append(view_name)
    for source_name, view_names in graph.items():
        graph[source_name] = sorted(view_names)
    return graph


def normalize_structure_type(raw_type: str) -> str:
    """Map catalog object-type names to standard NLD structure types."""
    structure_type_mapping = {
        "BASE TABLE": "TABLE",
    }
    upper_type = raw_type.upper() if raw_type else ""
    return structure_type_mapping.get(upper_type, upper_type)


class ConnectorStructureReader[CONNECTOR: DataConnector[Any]](ABC):
    """Abstract base class for extracting database structure metadata.

    This class defines the interface for extracting structure information
    (tables, views, columns, constraints) from various database connectors.

    Identifier-case contract: readers return nld-convention lowercase
    names for structures, fields and constraints. Engines that store
    unquoted identifiers in another case (Snowflake: uppercase) lower
    them on read; engines whose catalog already returns lowercase for
    nld-created objects (PostgreSQL, DuckDB) pass it through.
    """

    def __init__(self, connector: CONNECTOR) -> None:
        self._connector = connector

    @abstractmethod
    def extract_structures(self, **kwargs: Any) -> list[Structure]:
        """Extract structures from the data source.

        Returns:
            List of Structure objects.
        """
        ...

    def get_dependent_views(
        self,
        schema: str,
        object_name: str,
    ) -> list[str]:
        """Return the names of the views directly depending on an object.

        Engines without dependency detection return an empty list —
        their deploys cannot protect dependent views yet.
        """
        return []

    def get_all_dependent_views(
        self,
        schema: str,
    ) -> dict[str, list[str]]:
        """Return every direct view-dependency edge in the schema.

        Maps each source table/view name to the list of views that
        directly depend on it, read in one call rather than one
        ``get_dependent_views`` query per BFS frontier node. Engines
        without dependency detection return an empty mapping.
        """
        return {}

    def build_full_object_path(
        self,
        schema: str | None,
        object_name: str,
    ) -> str:
        """Build the connector's canonical fully-qualified object path.

        This is the cache key for prefetched live structures: two
        same-named objects in different schemas must never collide.
        Engines with a deeper hierarchy (e.g. Snowflake's database
        level) override this.
        """
        return f"{schema}.{object_name}" if schema else object_name

    def extract_all_structures(
        self,
        schema: str | None = None,
    ) -> dict[str, Structure]:
        """Extract every structure in the schema/dataset, keyed by full path.

        Reads the whole schema in one prefetch rather than the
        per-structure ``extract_structures(object_name=...)`` calls a
        deploy loop would otherwise issue once per table. The default
        implementation delegates to ``extract_structures`` without an
        ``object_name`` filter — correct for any connector whose
        batched detail queries are already schema-wide-capable and
        only gain scope (never shape) when unfiltered (PostgreSQL,
        DuckDB, BigQuery). Connectors that pay a real per-object
        round-trip cost when unfiltered (e.g. Snowflake) override this
        with a genuinely single-call batched implementation.

        Keys are ``build_full_object_path`` results, using each
        structure's own read-back schema when it carries one so a
        multi-schema read never collides on bare names.
        """
        structures = self.extract_structures(schema=schema)
        result: dict[str, Structure] = {}
        for structure in structures:
            structure_schema = (structure.properties or {}).get("schema") or schema
            result[
                self.build_full_object_path(
                    schema=structure_schema,
                    object_name=structure.name,
                )
            ] = structure
        return result


class SQLConnectorStructureReader[CONNECTOR: SQLDataConnector[Any]](
    ConnectorStructureReader[CONNECTOR],
):
    """Structure reader for SQL-based connectors.

    Adds SQL-specific capabilities such as active database awareness
    and filtering by database, schema, and object name.

    Subclasses must implement:
        - active_database: Property returning the current database name.
        - extract_structures: Method to extract structure metadata.
    """

    @property
    @abstractmethod
    def active_database(self) -> str | None:
        """Get the active database name from the connection.

        Returns:
            The database name, or None if not applicable.
        """
        ...

    @abstractmethod
    def extract_structures(
        self,
        database: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
        **kwargs: Any,
    ) -> list[Structure]:
        """Extract structures (tables/views) from the database.

        Args:
            database: Optional database name. When None, falls back
                to active_database.
            schema: Optional schema name to filter by.
            object_name: Optional table/view name to filter by.

        Returns:
            List of Structure objects representing tables and views.
        """
        ...
