import datetime
from typing import Any

from sqlglot import exp

from nld.utils.sqlglot.utils import identifier_list, literal_list, quote_table


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
