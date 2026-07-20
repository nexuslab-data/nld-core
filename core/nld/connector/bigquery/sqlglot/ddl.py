from sqlglot import exp

from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder
from nld.utils.sqlglot.utils import quoted_column_def, quoted_table


class BigQuerySqlglotDDLBuilder(BaseSqlglotDDLBuilder):
    """BigQuery-specific DDL query builder.

    Overrides existence checks because:
    - BigQuery rejects ``SELECT FROM ...`` (empty SELECT list).
    - BigQuery's ``INFORMATION_SCHEMA`` is scoped per dataset and must
      be referenced as ``<dataset>.INFORMATION_SCHEMA.<view>`` rather
      than the unqualified ``information_schema.<view>`` used by
      ANSI-flavored engines.
    """

    # Map ANSI-style user-declared type names to sqlglot canonical
    # aliases the bigquery dialect renders back to the intended
    # BigQuery native type. Callers declare ``TIMESTAMP`` expecting
    # BigQuery's TZ-aware TIMESTAMP, but sqlglot's bigquery dialect
    # interprets bare ``TIMESTAMP`` as BigQuery ``DATETIME`` (no TZ).
    # ``TIMESTAMPTZ`` is the canonical sqlglot name for a TZ-aware
    # timestamp and renders as BigQuery ``TIMESTAMP``.
    _TYPE_ALIASES: dict[str, str] = {
        "TIMESTAMP": "TIMESTAMPTZ",
    }

    def __init__(self) -> None:
        super().__init__(dialect="bigquery")

    @classmethod
    def _normalize_column_type(cls, data_type: str) -> str:
        """Remap caller-supplied type names to sqlglot canonical names.

        Length / precision suffixes (e.g. ``NUMERIC(10, 2)``) are
        preserved verbatim; only the base type is looked up in the
        alias table.
        """
        upper = data_type.upper()
        if "(" in upper:
            base, _, rest = upper.partition("(")
            aliased = cls._TYPE_ALIASES.get(base.strip(), base.strip())
            return f"{aliased}({rest}"
        return cls._TYPE_ALIASES.get(upper, upper)

    def build_create_table(
        self,
        schema: str,
        table: str,
        columns: list[tuple[str, str, bool]],
        primary_key_fields: list[str] | None = None,
        primary_key_name: str | None = None,
        if_not_exists: bool = False,
    ) -> str:
        """Build a CREATE TABLE with PRIMARY KEY NOT ENFORCED.

        BigQuery rejects ``PRIMARY KEY (...)`` without the
        ``NOT ENFORCED`` option ("Enforcement of primary keys is not
        supported"). The base builder emits an ``exp.PrimaryKey`` with
        no options, so we rebuild the AST here and set ``options`` on
        the PrimaryKey node — sqlglot's bigquery dialect then renders
        it as ``PRIMARY KEY (...) NOT ENFORCED``.
        """
        col_defs: list[exp.Expression] = [
            quoted_column_def(
                name=col_name,
                data_type=self._normalize_column_type(col_type),
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
                options=["NOT ENFORCED"],
            )
            if primary_key_name:
                pk_expression: exp.Expression = exp.Constraint(
                    this=exp.to_identifier(primary_key_name, quoted=True),
                    expressions=[pk_node],
                )
            else:
                pk_expression = pk_node
            col_defs.append(pk_expression)

        create = exp.Create(
            this=exp.Schema(
                this=quoted_table(schema=schema, table=table),
                expressions=col_defs,
            ),
            kind="TABLE",
            exists=if_not_exists,
        )
        return create.sql(dialect=self._dialect)

    def build_alter_column_type(
        self,
        schema: str,
        table: str,
        column_name: str,
        new_type: str,
    ) -> str:
        """Build a BigQuery ALTER COLUMN SET DATA TYPE statement.

        The base builder emits Postgres syntax
        ``ALTER COLUMN c TYPE T USING c::T`` which BigQuery rejects:
        BigQuery requires ``ALTER COLUMN c SET DATA TYPE T`` and has
        no ``USING`` clause. The ``new_type`` is normalized through
        the same alias table as ``build_create_table`` so caller
        declarations like ``TIMESTAMP`` render as BigQuery's TZ-aware
        ``TIMESTAMP`` (via the sqlglot ``TIMESTAMPTZ`` canonical).
        """
        table_ref = quoted_table(
            schema=schema,
            table=table,
        ).sql(dialect=self._dialect)
        col_id = exp.to_identifier(column_name, quoted=True).sql(
            dialect=self._dialect,
        )
        # ``new_type`` is a BigQuery-facing string (``FLOAT64``,
        # ``NUMERIC(10, 2)``, ...). ``sqlglot.exp.DataType.build`` is
        # dialect-sensitive — without ``dialect="bigquery"`` it fails
        # to parse BQ-only names like ``FLOAT64``. Pass it explicitly
        # and emit the normalized form straight through.
        normalized = self._normalize_column_type(new_type)
        return (
            f"ALTER TABLE {table_ref} ALTER COLUMN {col_id} SET DATA TYPE {normalized}"
        )

    def build_exists_query(
        self,
        schema: str,
        table: str,
    ) -> str:
        """Build a BigQuery-compatible table existence check."""
        table_lit = exp.convert(table).sql(dialect=self._dialect)
        return (
            f"SELECT COUNT(*) > 0 "
            f"FROM `{schema}`.INFORMATION_SCHEMA.TABLES "
            f"WHERE table_name = {table_lit}"
        )

    def build_schema_exists_query(
        self,
        schema: str,
    ) -> str:
        """Build a BigQuery-compatible dataset (schema) existence check.

        Uses the per-dataset ``__TABLES__`` metaview, which only needs
        ``bigquery.tables.list`` (already granted by ``dataEditor``).
        ``region-*.INFORMATION_SCHEMA.SCHEMATA`` would be more "ANSI"
        but requires project-level ``bigquery.resourceViewer``.

        Behaviour:
        - Dataset exists (with or without tables): the FROM clause is
          valid, ``COUNT(*) >= 0`` returns ``true`` → schema_exists.
        - Dataset does not exist: BigQuery raises a ``404 Not found``
          error which the caller catches as a missing schema.
        """
        return f"SELECT COUNT(*) >= 0 FROM `{schema}.__TABLES__`"

    def build_column_exists_query(
        self,
        schema: str,
        table: str,
        column_name: str,
    ) -> str:
        """Build a BigQuery-compatible column existence check."""
        table_lit = exp.convert(table).sql(dialect=self._dialect)
        column_lit = exp.convert(column_name).sql(dialect=self._dialect)
        return (
            f"SELECT COUNT(*) > 0 "
            f"FROM `{schema}`.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE table_name = {table_lit} "
            f"AND column_name = {column_lit}"
        )

    def build_column_names_query(
        self,
        schema: str,
        table: str,
    ) -> str:
        """Build a BigQuery-compatible column-names listing."""
        table_lit = exp.convert(table).sql(dialect=self._dialect)
        return (
            f"SELECT column_name "
            f"FROM `{schema}`.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE table_name = {table_lit} "
            f"ORDER BY ordinal_position"
        )
