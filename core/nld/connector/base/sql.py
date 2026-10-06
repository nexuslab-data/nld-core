_CONNECTOR_TYPE_TO_SQLGLOT_DIALECT: dict[str, str] = {
    "bigquery": "bigquery",
    "duckdb": "duckdb",
    "postgresql": "postgres",
    "snowflake": "snowflake",
    "sqlite": "sqlite",
}


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
