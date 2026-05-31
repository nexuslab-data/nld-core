from sqlglot import exp

from nld.utils.sqlglot.utils import quoted_column_def, quoted_table


class BaseSqlglotDDLBuilder:
    """Base DDL query builder with default behavior.

    Provides methods for building DDL queries using sqlglot. Subclasses
    can override methods to provide connector-specific SQL syntax.
    """

    def __init__(self, dialect: str) -> None:
        self._dialect = dialect

    def build_exists_query(
        self,
        schema: str,
        table: str,
    ) -> str:
        """Build a query to check if a table exists."""
        schema_lit = exp.convert(schema).sql(dialect=self._dialect)
        table_lit = exp.convert(table).sql(dialect=self._dialect)
        return (
            f"SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            f"WHERE table_schema = {schema_lit} "
            f"AND table_name = {table_lit})"
        )

    def build_schema_exists_query(
        self,
        schema: str,
    ) -> str:
        """Build a query to check if a schema exists."""
        schema_lit = exp.convert(schema).sql(dialect=self._dialect)
        return (
            f"SELECT EXISTS (SELECT FROM information_schema.schemata "
            f"WHERE schema_name = {schema_lit})"
        )

    def build_column_exists_query(
        self,
        schema: str,
        table: str,
        column_name: str,
    ) -> str:
        """Build a query to check if a column exists in a table."""
        schema_lit = exp.convert(schema).sql(dialect=self._dialect)
        table_lit = exp.convert(table).sql(dialect=self._dialect)
        column_lit = exp.convert(column_name).sql(dialect=self._dialect)
        return (
            f"SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            f"WHERE table_schema = {schema_lit} "
            f"AND table_name = {table_lit} "
            f"AND column_name = {column_lit})"
        )

    def build_create_table(
        self,
        schema: str,
        table: str,
        columns: list[tuple[str, str, bool]],
        primary_key_fields: list[str] | None = None,
        primary_key_name: str | None = None,
        if_not_exists: bool = False,
    ) -> str:
        """Build a CREATE TABLE statement using sqlglot AST."""
        col_defs: list[exp.Expression] = [
            quoted_column_def(
                name=col_name,
                data_type=col_type,
                not_null=col_not_null,
            )
            for col_name, col_type, col_not_null in columns
        ]

        if primary_key_fields:
            pk_node = exp.PrimaryKey(
                expressions=[
                    exp.to_identifier(field, quoted=True)
                    for field in primary_key_fields
                ],
            )
            if primary_key_name:
                pk_expression: exp.Expression = exp.Constraint(
                    this=exp.to_identifier(
                        primary_key_name,
                        quoted=True,
                    ),
                    expressions=[pk_node],
                )
            else:
                pk_expression = pk_node
            col_defs.append(pk_expression)

        create = exp.Create(
            this=exp.Schema(
                this=quoted_table(
                    schema=schema,
                    table=table,
                ),
                expressions=col_defs,
            ),
            kind="TABLE",
            exists=if_not_exists,
        )
        return create.sql(dialect=self._dialect)

    def build_drop_table(
        self,
        schema: str,
        table: str,
        if_exists: bool = False,
    ) -> str:
        """Build a DROP TABLE statement."""
        drop = exp.Drop(
            this=quoted_table(
                schema=schema,
                table=table,
            ),
            kind="TABLE",
            exists=if_exists,
        )
        return drop.sql(dialect=self._dialect)

    def build_truncate_table(
        self,
        schema: str,
        table: str,
    ) -> str:
        """Build a TRUNCATE TABLE statement."""
        truncate = exp.TruncateTable(
            expressions=[
                quoted_table(
                    schema=schema,
                    table=table,
                ),
            ],
        )
        return truncate.sql(dialect=self._dialect)

    def build_create_index(
        self,
        index_name: str,
        schema: str,
        table: str,
        columns: list[str],
        unique: bool = False,
        if_not_exists: bool = False,
    ) -> str:
        """Build a CREATE INDEX statement."""
        unique_kw = "UNIQUE " if unique else ""
        if_not_exists_kw = "IF NOT EXISTS " if if_not_exists else ""
        table_ref = quoted_table(
            schema=schema,
            table=table,
        ).sql(dialect=self._dialect)
        index_id = exp.to_identifier(
            index_name,
            quoted=True,
        ).sql(dialect=self._dialect)
        cols = ", ".join(
            exp.to_identifier(col, quoted=True).sql(dialect=self._dialect)
            for col in columns
        )
        return (
            f"CREATE {unique_kw}INDEX {if_not_exists_kw}"
            f"{index_id} ON {table_ref} ({cols})"
        )

    def build_drop_index(
        self,
        schema: str,
        index_name: str,
    ) -> str:
        """Build a DROP INDEX statement with schema qualification."""
        schema_id = exp.to_identifier(
            schema,
            quoted=True,
        ).sql(dialect=self._dialect)
        index_id = exp.to_identifier(
            index_name,
            quoted=True,
        ).sql(dialect=self._dialect)
        return f"DROP INDEX {schema_id}.{index_id}"

    def build_alter_add_column(
        self,
        schema: str,
        table: str,
        column_name: str,
        data_type: str,
        not_null: bool = False,
        default_value: str | None = None,
    ) -> str:
        """Build an ALTER TABLE ADD COLUMN statement."""
        table_ref = quoted_table(
            schema=schema,
            table=table,
        ).sql(dialect=self._dialect)
        col_id = exp.to_identifier(
            column_name,
            quoted=True,
        ).sql(dialect=self._dialect)
        default_clause = (
            f" DEFAULT {default_value}" if default_value is not None else ""
        )
        not_null_clause = " NOT NULL" if not_null else ""
        return (
            f"ALTER TABLE {table_ref} ADD COLUMN"
            f" {col_id} {data_type}{default_clause}{not_null_clause}"
        )

    def build_alter_drop_column(
        self,
        schema: str,
        table: str,
        column_name: str,
    ) -> str:
        """Build an ALTER TABLE DROP COLUMN statement."""
        table_ref = quoted_table(
            schema=schema,
            table=table,
        ).sql(dialect=self._dialect)
        col_id = exp.to_identifier(
            column_name,
            quoted=True,
        ).sql(dialect=self._dialect)
        return f"ALTER TABLE {table_ref} DROP COLUMN {col_id}"

    def build_alter_column_type(
        self,
        schema: str,
        table: str,
        column_name: str,
        new_type: str,
    ) -> str:
        """Build an ALTER TABLE ALTER COLUMN TYPE statement."""
        table_ref = quoted_table(
            schema=schema,
            table=table,
        ).sql(dialect=self._dialect)
        col_id = exp.to_identifier(
            column_name,
            quoted=True,
        ).sql(dialect=self._dialect)
        return (
            f"ALTER TABLE {table_ref} ALTER COLUMN {col_id} "
            f"TYPE {new_type} USING {col_id}::{new_type}"
        )

    def build_alter_set_not_null(
        self,
        schema: str,
        table: str,
        column_name: str,
    ) -> str:
        """Build an ALTER TABLE ALTER COLUMN SET NOT NULL statement."""
        table_ref = quoted_table(
            schema=schema,
            table=table,
        ).sql(dialect=self._dialect)
        col_id = exp.to_identifier(
            column_name,
            quoted=True,
        ).sql(dialect=self._dialect)
        return f"ALTER TABLE {table_ref} ALTER COLUMN {col_id} SET NOT NULL"

    def build_alter_drop_not_null(
        self,
        schema: str,
        table: str,
        column_name: str,
    ) -> str:
        """Build an ALTER TABLE ALTER COLUMN DROP NOT NULL statement."""
        table_ref = quoted_table(
            schema=schema,
            table=table,
        ).sql(dialect=self._dialect)
        col_id = exp.to_identifier(
            column_name,
            quoted=True,
        ).sql(dialect=self._dialect)
        return f"ALTER TABLE {table_ref} ALTER COLUMN {col_id} DROP NOT NULL"

    def build_alter_add_constraint(
        self,
        schema: str,
        table: str,
        constraint_name: str,
        constraint_type: str,
        columns: list[str],
    ) -> str:
        """Build an ALTER TABLE ADD CONSTRAINT statement."""
        table_ref = quoted_table(
            schema=schema,
            table=table,
        ).sql(dialect=self._dialect)
        constraint_id = exp.to_identifier(
            constraint_name,
            quoted=True,
        ).sql(dialect=self._dialect)
        cols = ", ".join(
            exp.to_identifier(col, quoted=True).sql(dialect=self._dialect)
            for col in columns
        )
        return (
            f"ALTER TABLE {table_ref} ADD CONSTRAINT "
            f"{constraint_id} {constraint_type} ({cols})"
        )

    def build_alter_drop_constraint(
        self,
        schema: str,
        table: str,
        constraint_name: str,
    ) -> str:
        """Build an ALTER TABLE DROP CONSTRAINT statement."""
        table_ref = quoted_table(
            schema=schema,
            table=table,
        ).sql(dialect=self._dialect)
        constraint_id = exp.to_identifier(
            constraint_name,
            quoted=True,
        ).sql(dialect=self._dialect)
        return f"ALTER TABLE {table_ref} DROP CONSTRAINT {constraint_id}"

    def build_create_schema(
        self,
        schema: str,
        if_not_exists: bool = False,
    ) -> str:
        """Build a CREATE SCHEMA statement."""
        if_not_exists_kw = "IF NOT EXISTS " if if_not_exists else ""
        schema_id = exp.to_identifier(
            schema,
            quoted=True,
        ).sql(dialect=self._dialect)
        return f"CREATE SCHEMA {if_not_exists_kw}{schema_id}"
