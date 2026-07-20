import datetime
from typing import Any

from sqlglot import exp

from nld.utils.sqlglot.utils import (
    identifier_list,
    literal_list,
    quote_table,
    quoted_table,
)


class BaseSqlglotDMLBuilder:
    """Base DML query builder with default behavior.

    Provides methods for building DML queries using sqlglot. Subclasses
    can override methods to provide connector-specific SQL syntax.
    """

    def __init__(self, dialect: str) -> None:
        self._dialect = dialect

    def build_timestamp_condition(
        self,
        table_qualifier: str,
        field_name: str,
        start_timestamp: datetime.datetime | None,
        end_timestamp: datetime.datetime | None,
    ) -> exp.Expression | None:
        """Build a >= start AND < end condition for timestamps."""
        conditions: list[exp.Expression] = []

        column = exp.Column(
            this=exp.to_identifier(field_name),
            table=exp.to_identifier(table_qualifier),
        )

        if start_timestamp is not None:
            conditions.append(
                exp.GTE(
                    this=column.copy(),
                    expression=exp.convert(start_timestamp.isoformat()),
                )
            )

        if end_timestamp is not None:
            conditions.append(
                exp.LT(
                    this=column.copy(),
                    expression=exp.convert(end_timestamp.isoformat()),
                )
            )

        if not conditions:
            return None

        result = conditions[0]
        for condition in conditions[1:]:
            result = exp.And(
                this=result,
                expression=condition,
            )
        return result

    def equality_clause(
        self,
        field: str,
        value: Any,
    ) -> str:
        """Build a quoted_field = literal_value expression."""
        return exp.EQ(
            this=exp.to_identifier(field, quoted=True),
            expression=exp.convert(value),
        ).sql(dialect=self._dialect)

    def and_clause(
        self,
        conditions: list[str],
    ) -> str:
        """Join pre-built condition strings with AND."""
        return " AND ".join(conditions)

    def build_values_clause(
        self,
        rows: list[tuple[Any, ...]],
    ) -> str:
        """Build a VALUES clause from a list of row tuples."""
        row_strings = [
            f"({literal_list(list(row), dialect=self._dialect)})" for row in rows
        ]
        return "VALUES " + ", ".join(row_strings)

    def build_on_conflict_clause(
        self,
        insert_column_list: list[str],
        conflict_merge_fields: list[str],
        table_name: str,
        exclude_from_update: list[str] | None = None,
        expression_overrides: dict[str, str] | None = None,
        exclude_from_match: list[str] | None = None,
    ) -> str:
        """Build an ON CONFLICT ... DO UPDATE SET ... WHERE clause.

        Includes a WHERE clause using IS DISTINCT FROM so that rows
        are only updated when at least one data column has changed.

        Args:
            insert_column_list: all columns being inserted.
            conflict_merge_fields: columns forming the conflict target.
            table_name: unqualified target table name, used as the
                row qualifier in the WHERE clause.
            exclude_from_update: columns to omit from the UPDATE SET
                clause entirely (e.g. insert-only timestamp fields).
            expression_overrides: columns to set to a custom SQL
                expression instead of EXCLUDED.col (e.g.
                {"ts_updated_at": "CURRENT_TIMESTAMP"}).
            exclude_from_match: columns to keep in UPDATE SET but
                exclude from the WHERE change-detection clause.

        Raises:
            ValueError: If all columns are conflict keys and there
                are no columns left to update.
        """
        excluded_set = set(exclude_from_update or [])
        overrides = expression_overrides or {}
        columns_to_update = [
            column
            for column in insert_column_list
            if column not in conflict_merge_fields and column not in excluded_set
        ]
        if len(columns_to_update) == 0:
            keys = ", ".join(conflict_merge_fields)
            raise ValueError(
                f"On conflict part cannot be generated without any columns "
                f"to update. All columns are listed as key for update: {keys}"
            )

        update_expressions: list[exp.Expression] = []
        for col in columns_to_update:
            if col in overrides:
                update_expressions.append(
                    exp.EQ(
                        this=exp.to_identifier(col, quoted=True),
                        expression=exp.Var(this=overrides[col]),
                    ),
                )
            else:
                update_expressions.append(
                    exp.EQ(
                        this=exp.to_identifier(col, quoted=True),
                        expression=exp.Column(
                            this=exp.to_identifier(col, quoted=True),
                            table=exp.to_identifier("EXCLUDED"),
                        ),
                    ),
                )

        exclude_from_match_set = set(exclude_from_match or [])
        data_columns = [
            col
            for col in columns_to_update
            if col not in overrides and col not in exclude_from_match_set
        ]
        where_clause = None
        if data_columns:
            change_conditions = [
                exp.NullSafeNEQ(
                    this=exp.Column(
                        this=exp.to_identifier(col, quoted=True),
                        table=exp.to_identifier(table_name),
                    ),
                    expression=exp.Column(
                        this=exp.to_identifier(col, quoted=True),
                        table=exp.to_identifier("EXCLUDED"),
                    ),
                )
                for col in data_columns
            ]
            combined: exp.Expression = change_conditions[0]
            for condition in change_conditions[1:]:
                combined = exp.Or(
                    this=combined,
                    expression=condition,
                )
            where_clause = exp.Where(this=combined)

        on_conflict = exp.OnConflict(
            conflict_keys=[
                exp.to_identifier(field, quoted=True) for field in conflict_merge_fields
            ],
            action=exp.Var(this="DO UPDATE"),
            expressions=update_expressions,
            where=where_clause,
        )
        return on_conflict.sql(dialect=self._dialect)

    def build_count_query(
        self,
        table_path: str,
        where_conditions: dict[str, Any] | None = None,
    ) -> str:
        """Build a SELECT COUNT(*) query with optional WHERE conditions.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            where_conditions: optional mapping of column names to values
                for equality filtering.

        Returns:
            The rendered SQL query string.
        """
        count_expr = exp.Count(this=exp.Star())
        query = exp.Select(
            expressions=[exp.Alias(this=count_expr, alias="row_count")],
        ).from_(table_path)

        if where_conditions:
            condition: exp.Expression | None = None
            for col, val in where_conditions.items():
                eq = exp.EQ(
                    this=exp.to_identifier(col, quoted=True),
                    expression=exp.convert(val),
                )
                if condition is None:
                    condition = eq
                else:
                    condition = exp.And(
                        this=condition,
                        expression=eq,
                    )
            if condition is not None:
                query = query.where(condition)

        return query.sql(dialect=self._dialect)

    def build_key_in_condition(
        self,
        table_qualifier: str,
        field_name: str,
        keys: list[str],
    ) -> exp.Expression | None:
        """Build a column IN (key1, key2, ...) condition."""
        if not keys:
            return None

        column = exp.Column(
            this=exp.to_identifier(field_name),
            table=exp.to_identifier(table_qualifier),
        )

        return exp.In(
            this=column,
            expressions=[exp.convert(key) for key in keys],
        )

    def build_bulk_insert_query(
        self,
        schema_name: str,
        table_name: str,
        insert_column_list: list[str],
        rows: list[tuple[Any, ...]],
        conflict_merge_fields: list[str] | None = None,
    ) -> str:
        """Build a complete INSERT statement with inlined values.

        Args:
            schema_name: target schema name.
            table_name: target table name.
            insert_column_list: columns to insert into.
            rows: list of row tuples to insert.
            conflict_merge_fields: optional list of conflict
                target columns for ON CONFLICT.

        Returns:
            A complete INSERT INTO ... VALUES ... SQL string.
        """
        on_conflict = ""
        if conflict_merge_fields is not None:
            if len(conflict_merge_fields) > 0:
                on_conflict = self.build_on_conflict_clause(
                    insert_column_list=insert_column_list,
                    conflict_merge_fields=conflict_merge_fields,
                    table_name=table_name,
                )

        table_ref = quote_table(
            schema=schema_name,
            table=table_name,
            dialect=self._dialect,
        )
        columns = identifier_list(
            insert_column_list,
            dialect=self._dialect,
        )
        values = self.build_values_clause(rows)

        return f"INSERT INTO {table_ref} ({columns}) {values} {on_conflict};"

    # -- Data-audit / profiling query builders -------------------------------
    #
    # These build the aggregate queries that a data profiler runs to measure a
    # table (coverage, distinct counts, value ranges, distributions, date span).
    # They are dialect-aware through sqlglot; a connector-specific DML builder
    # may override them (e.g. a different random-sampling expression) when its
    # engine needs it.

    @staticmethod
    def _audit_column(name: str) -> exp.Column:
        """Quoted column reference used by the audit aggregates."""
        return exp.Column(this=exp.to_identifier(name, quoted=True))

    def build_audit_source(
        self,
        schema_name: str,
        table_name: str,
        sample_size: int | None = None,
    ) -> exp.Expression:
        """Build the FROM source for audit queries.

        Returns the quoted table reference, or — when ``sample_size`` is set —
        a ``(SELECT * FROM <table> ORDER BY RANDOM() LIMIT N) AS src`` subquery.
        Override in a connector-specific builder to use an engine-native
        sampling clause (e.g. ``TABLESAMPLE``) or random function.
        """
        table_expr = quoted_table(schema=schema_name, table=table_name)
        if sample_size is None:
            return table_expr
        inner = (
            exp.Select(expressions=[exp.Star()])
            .from_(table_expr)
            .order_by(exp.func("RANDOM"))
            .limit(sample_size)
        )
        return exp.Subquery(
            this=inner,
            alias=exp.TableAlias(this=exp.to_identifier("src")),
        )

    def build_audit_coverage_query(
        self,
        schema_name: str,
        table_name: str,
        column_names: list[str],
        sample_size: int | None = None,
    ) -> str:
        """Build the single coverage query for all profiled columns.

        Emits ``count(*) AS total`` plus, per column at position ``i``,
        ``count(col) AS nn_<i>`` and ``count(DISTINCT col) AS dc_<i>``.
        """
        source = self.build_audit_source(schema_name, table_name, sample_size)
        expressions: list[exp.Expression] = [
            exp.alias_(exp.Count(this=exp.Star()), "total")
        ]
        for index, name in enumerate(column_names):
            column = self._audit_column(name)
            expressions.append(exp.alias_(exp.Count(this=column.copy()), f"nn_{index}"))
            expressions.append(
                exp.alias_(
                    exp.Count(this=exp.Distinct(expressions=[column.copy()])),
                    f"dc_{index}",
                )
            )
        return (
            exp.Select(expressions=expressions).from_(source).sql(dialect=self._dialect)
        )

    def build_audit_min_max_query(
        self,
        schema_name: str,
        table_name: str,
        column_names: list[str],
        sample_size: int | None = None,
    ) -> str:
        """Build the min/max query for the given (numeric/temporal) columns.

        Emits ``min(col) AS min_<i>`` / ``max(col) AS max_<i>`` per column at
        position ``i``. Returns an empty string when no columns are provided.
        """
        if not column_names:
            return ""
        source = self.build_audit_source(schema_name, table_name, sample_size)
        expressions: list[exp.Expression] = []
        for index, name in enumerate(column_names):
            column = self._audit_column(name)
            expressions.append(exp.alias_(exp.Min(this=column.copy()), f"min_{index}"))
            expressions.append(exp.alias_(exp.Max(this=column.copy()), f"max_{index}"))
        return (
            exp.Select(expressions=expressions).from_(source).sql(dialect=self._dialect)
        )

    def build_audit_distribution_query(
        self,
        schema_name: str,
        table_name: str,
        column_name: str,
        top_n: int,
        sample_size: int | None = None,
    ) -> str:
        """Build a top-N value distribution query for one column.

        Counts non-null values grouped by the column, ordered by frequency
        descending, capped at ``top_n``. The null share is intentionally
        excluded — it is already captured by the column's coverage.
        """
        source = self.build_audit_source(schema_name, table_name, sample_size)
        column = self._audit_column(column_name)
        query = (
            exp.Select(
                expressions=[
                    exp.alias_(column.copy(), "value"),
                    exp.alias_(exp.Count(this=exp.Star()), "count"),
                ]
            )
            .from_(source)
            .where(exp.Not(this=exp.Is(this=column.copy(), expression=exp.Null())))
            .group_by(column.copy())
            .order_by(exp.column("count").desc())
            .limit(top_n)
        )
        return query.sql(dialect=self._dialect)

    def build_audit_date_span_query(
        self,
        schema_name: str,
        table_name: str,
        column_name: str,
        sample_size: int | None = None,
    ) -> str:
        """Build a min/max query over a single date/timestamp column."""
        source = self.build_audit_source(schema_name, table_name, sample_size)
        column = self._audit_column(column_name)
        return (
            exp.Select(
                expressions=[
                    exp.alias_(exp.Min(this=column.copy()), "date_from"),
                    exp.alias_(exp.Max(this=column.copy()), "date_to"),
                ]
            )
            .from_(source)
            .sql(dialect=self._dialect)
        )

    def build_insert_from_select_query(
        self,
        schema_name: str,
        table_name: str,
        selection_query: str,
        insert_column_list: list[str],
        conflict_merge_fields: list[str] | None = None,
        exclude_from_update: list[str] | None = None,
        expression_overrides: dict[str, str] | None = None,
        exclude_from_match: list[str] | None = None,
    ) -> str:
        """Build an INSERT INTO ... SELECT ... statement.

        Args:
            schema_name: target schema name.
            table_name: target table name.
            selection_query: the SELECT query providing data.
            insert_column_list: columns to insert into.
            conflict_merge_fields: optional list of conflict
                target columns for ON CONFLICT.
            exclude_from_update: columns to omit from the
                UPDATE SET clause.
            expression_overrides: columns to set to a custom
                SQL expression instead of EXCLUDED.col.
            exclude_from_match: columns to keep in UPDATE SET
                but exclude from change-detection.

        Returns:
            A complete INSERT INTO ... SELECT ... SQL string.
        """
        on_conflict = ""
        if conflict_merge_fields is not None:
            if len(conflict_merge_fields) > 0:
                on_conflict = self.build_on_conflict_clause(
                    insert_column_list=insert_column_list,
                    conflict_merge_fields=conflict_merge_fields,
                    table_name=table_name,
                    exclude_from_update=exclude_from_update,
                    expression_overrides=expression_overrides,
                    exclude_from_match=exclude_from_match,
                )

        table_ref = quote_table(
            schema=schema_name,
            table=table_name,
            dialect=self._dialect,
        )
        columns = identifier_list(
            insert_column_list,
            dialect=self._dialect,
        )

        return (
            f"INSERT INTO {table_ref} ({columns}) \n{selection_query}\n{on_conflict};"
        )

    def build_mark_absent_rows_deleted_query(
        self,
        table_path: str,
        sql_query: str,
        key_columns: list[str],
        deletion_flag_column: str,
    ) -> str:
        """Build the logical-delete UPDATE for rows absent from the query.

        Flags every target row whose key is not returned by ``sql_query``.
        The ``NOT EXISTS`` form is used instead of a multi-column tuple
        ``NOT IN`` (unsupported against a subquery on BigQuery), and the
        already-flagged guard uses ``COALESCE(flag, FALSE) = FALSE``
        rather than ``IS NOT TRUE`` (Snowflake has no ``IS [ NOT ] TRUE``
        predicate). Identifiers stay unquoted here — the default suits
        Postgres and Snowflake; BigQuery overrides this to quote them.
        """
        join_conditions = " AND ".join(
            f"_src.{column} = {table_path}.{column}" for column in key_columns
        )
        return (
            f"UPDATE {table_path} "
            f"SET {deletion_flag_column} = TRUE "
            f"WHERE COALESCE({deletion_flag_column}, FALSE) = FALSE "
            f"AND NOT EXISTS ("
            f"SELECT 1 FROM ({sql_query}) AS _src "
            f"WHERE {join_conditions}"
            f")"
        )
