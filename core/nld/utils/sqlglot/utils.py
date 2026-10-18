from typing import Any

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

POSTGRES_DIALECT = "postgres"
SNOWFLAKE_DIALECT = "snowflake"


def _safe_parse_one(
    query: str,
    dialect: str | None = None,
) -> exp.Expression | None:
    """Parse a single SQL statement, returning None when it cannot be parsed."""
    try:
        return parse_one(query, dialect=dialect)
    except ParseError:
        return None


def is_select_query(
    query: str,
    dialect: str | None = None,
) -> bool:
    """Return True when the query is a read-only SELECT/WITH statement.

    The query is parsed through sqlglot so comments, formatting and CTEs
    do not affect the detection, unlike a naive leading-keyword check.
    """
    parsed = _safe_parse_one(
        query=query,
        dialect=dialect,
    )
    return isinstance(parsed, exp.Select | exp.Union | exp.Subquery)


def get_query_statement_type(
    query: str,
    dialect: str | None = None,
) -> str:
    """Return the upper-cased statement type (SELECT, INSERT, ...) of a query."""
    parsed = _safe_parse_one(
        query=query,
        dialect=dialect,
    )
    if parsed is None:
        return "UNKNOWN"
    return parsed.key.upper()


def find_table_reference(
    parsed: exp.Expression,
    table_name: str,
    database_name: str | None = None,
) -> exp.Table | None:
    """Find a table node in the parsed query matching the given name.

    When ``database_name`` is given, a node qualified with a database
    must name that one: ``DB_A.RAW.ORDERS`` is not a read of ``ORDERS``
    from ``DB_B``. A node without database still matches by name.
    """
    for table_node in parsed.find_all(exp.Table):
        if _is_table_read(
            database_name=database_name,
            table_name=table_name,
            table_node=table_node,
        ):
            return table_node
    return None


def find_table_references(
    parsed: exp.Expression,
    table_name: str,
    database_name: str | None = None,
) -> list[exp.Table]:
    """Find every table node reading ``table_name``, CTE references excluded.

    A query may read the same table several times (UNION branches,
    self-joins, subqueries). A table reference without schema whose name
    is the name of a CTE of the query reads the CTE, not the table, so it
    is left out. For example in ``WITH orders AS (SELECT * FROM s.orders)
    SELECT * FROM orders`` only ``s.orders`` is returned.

    When ``database_name`` is given, a node qualified with another
    database is left out as well, as in ``find_table_reference``.
    """
    cte_names = {cte.alias_or_name.lower() for cte in parsed.find_all(exp.CTE)}
    return [
        table_node
        for table_node in parsed.find_all(exp.Table)
        if _is_table_read(
            database_name=database_name,
            table_name=table_name,
            table_node=table_node,
        )
        and (table_node.db or table_node.name.lower() not in cte_names)
    ]


def _is_table_read(
    database_name: str | None,
    table_name: str,
    table_node: exp.Table,
) -> bool:
    """Whether the node reads the table, in the database when it names one."""
    if table_node.name.lower() != table_name.lower():
        return False
    if database_name is None or not table_node.catalog:
        return True
    return table_node.catalog.lower() == database_name.lower()


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
