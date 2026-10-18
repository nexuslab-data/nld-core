_CONNECTOR_TYPE_TO_SQLGLOT_DIALECT: dict[str, str] = {
    "bigquery": "bigquery",
    "duckdb": "duckdb",
    "postgresql": "postgres",
    "snowflake": "snowflake",
    "sqlite": "sqlite",
}

_CROSS_DATABASE_READ_CONNECTOR_TYPES: frozenset[str] = frozenset({"snowflake"})


def resolve_sqlglot_dialect(connector_type: str) -> str:
    """Resolve a connector type to its sqlglot dialect name.

    Args:
        connector_type: The connector type identifier (e.g. "postgresql").

    Raises:
        ValueError: If the connector type has no known sqlglot dialect.
    """
    dialect = _CONNECTOR_TYPE_TO_SQLGLOT_DIALECT.get(connector_type)
    if dialect is None:
        raise ValueError(
            f"No sqlglot dialect mapping found for connector type "
            f"'{connector_type}'. Known types: "
            f"{list(_CONNECTOR_TYPE_TO_SQLGLOT_DIALECT.keys())}"
        )
    return dialect


def supports_cross_database_read(connector_type: str | None) -> bool:
    """Whether the engine reads another database's tables in the same query.

    Snowflake reads ``database.schema.table`` across the databases of an
    account. PostgreSQL cannot query across databases, and the BigQuery
    project and DuckDB attached catalog equivalents are not supported.
    An unknown engine is assumed not to support it.
    """
    return connector_type in _CROSS_DATABASE_READ_CONNECTOR_TYPES
