from typing import Any

from sqlglot import exp

POSTGRES_DIALECT = "postgres"
SNOWFLAKE_DIALECT = "snowflake"


def find_table_reference(
    parsed: exp.Expression,
    table_name: str,
) -> exp.Table | None:
    """Find a table node in the parsed query matching the given name."""
    for table_node in parsed.find_all(exp.Table):
        if table_node.name.lower() == table_name.lower():
            return table_node
    return None


def get_table_alias_or_name(table_node: exp.Table) -> str:
    """Get the alias of a table, or its name if no alias."""
    if table_node.alias:
        return table_node.alias
    return table_node.name


def quoted_column_def(
    name: str,
    data_type: str,
    not_null: bool = False,
) -> exp.ColumnDef:
    """Build a ColumnDef node with quoted identifier."""
    constraints = []
    if not_null:
        constraints.append(exp.ColumnConstraint(kind=exp.NotNullColumnConstraint()))
    return exp.ColumnDef(
        this=exp.to_identifier(name, quoted=True),
        kind=exp.DataType.build(data_type),
        constraints=constraints if constraints else None,
    )


def quoted_table(
    schema: str,
    table: str,
) -> exp.Table:
    """Build a sqlglot Table node with quoted identifiers."""
    return exp.Table(
        this=exp.to_identifier(table, quoted=True),
        db=exp.to_identifier(schema, quoted=True),
    )


def quote_identifier(
    name: str,
    dialect: str,
) -> str:
    """Quote a single SQL identifier for the given dialect."""
    return exp.to_identifier(
        name,
        quoted=True,
    ).sql(dialect=dialect)


def quote_table(
    schema: str,
    table: str,
    dialect: str,
) -> str:
    """Build a fully qualified quoted table reference."""
    return quoted_table(
        schema=schema,
        table=table,
    ).sql(dialect=dialect)


def literal_value(
    value: Any,
    dialect: str,
) -> str:
    """Convert a Python value to a SQL literal string."""
    return exp.convert(value).sql(dialect=dialect)


def identifier_list(
    names: list[str],
    dialect: str,
) -> str:
    """Build a comma-separated list of quoted identifiers."""
    identifiers = [exp.to_identifier(name, quoted=True) for name in names]
    return ", ".join(node.sql(dialect=dialect) for node in identifiers)


def literal_list(
    values: list[Any],
    dialect: str,
) -> str:
    """Build a comma-separated list of SQL literals."""
    return ", ".join(exp.convert(value).sql(dialect=dialect) for value in values)
