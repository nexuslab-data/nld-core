import sqlglot
from sqlglot import exp

from nld.flow.definition.flow_definition import (
    DataFlowStructurePredecessor,
    resolve_master_predecessors,
)
from nld.flow.incremental.base.sql_filter_manager import IncrementalSqlFilterManager
from nld.flow.incremental.impl.by_target_period.logic import ByTargetPeriodOptions
from nld.flow.incremental.impl.by_target_period.sql_builder import (
    build_period_condition,
    resolve_column_kind,
)
from nld.flow.incremental.impl.by_target_period.state import (
    ByTargetPeriodProcessingState,
)
from nld.structure import Structure
from nld.utils.sqlglot.utils import find_table_references, get_table_alias_or_name


def resolve_master_table_references(
    parsed: exp.Expression,
    predecessors: dict[str, DataFlowStructurePredecessor],
    input_database_names: dict[str, str] | None = None,
) -> list[tuple[str, Structure, list[exp.Table]]]:
    """Return each MASTER predecessor with every table node reading it.

    The query may read a MASTER several times (UNION branches, self-joins,
    subqueries): every read is returned so that every one is filtered.
    Tables are matched by name, a read qualified with another database
    than the input's declared one excepted, so the ambiguous cases are
    refused rather than guessed: two MASTER predecessors sharing a name,
    or one name read from several database and schema locations.

    Raises:
        ValueError: if the flow has no MASTER predecessor, if a MASTER is
            not read by the query, or if a match is ambiguous.
    """
    masters = resolve_master_predecessors(predecessors)
    if not masters:
        raise ValueError(
            "by_target_period filtering needs at least one MASTER "
            "predecessor holding the period column."
        )
    resolved: list[tuple[str, Structure, list[exp.Table]]] = []
    seen_names: dict[str, str] = {}
    for predecessor_name, master_predecessor in masters:
        master_structure = master_predecessor.full_path.resolve(
            entity_type="structure",
        )
        table_name = master_structure.name.lower()
        if table_name in seen_names:
            raise ValueError(
                f"MASTER predecessors '{seen_names[table_name]}' and "
                f"'{predecessor_name}' share the table name "
                f"'{master_structure.name}': by_target_period cannot tell "
                f"their reads apart in the SQL query."
            )
        seen_names[table_name] = predecessor_name
        table_nodes = find_table_references(
            parsed,
            table_name=master_structure.name,
            database_name=(input_database_names or {}).get(predecessor_name),
        )
        if not table_nodes:
            raise ValueError(
                f"Master predecessor table '{master_structure.name}' "
                f"not found in the SQL query."
            )
        locations = {
            ".".join(
                part for part in (table_node.catalog, table_node.db) if part
            ).lower()
            for table_node in table_nodes
        }
        if len(locations) > 1:
            raise ValueError(
                f"Master predecessor table '{master_structure.name}' is read "
                f"from several schemas ({', '.join(sorted(locations))}): "
                f"by_target_period cannot tell which one holds the periods."
            )
        resolved.append((predecessor_name, master_structure, table_nodes))
    return resolved


class ByTargetPeriodSqlFilterManager(IncrementalSqlFilterManager):
    """Period-based incremental SQL filter.

    Restricts every MASTER predecessor table to the periods the run
    replaces, with one half-open range predicate per group of contiguous
    periods on the source period column, added to the SELECT reading the
    table (a CTE, a subquery or a UNION branch included). Every strategy
    filters, FULL included, and an empty selection filters out every row:
    the filter never turns into an unfiltered load.
    """

    def __init__(
        self,
        processing_state: ByTargetPeriodProcessingState,
        options: ByTargetPeriodOptions,
    ) -> None:
        self.processing_state = processing_state
        self.options = options

    def apply_filter(
        self,
        sql_query: str,
        predecessors: dict[str, DataFlowStructurePredecessor],
        dialect: str,
        input_database_names: dict[str, str] | None = None,
    ) -> str:
        """Apply the period filtering to a SQL query.

        Raises:
            ValueError: if the flow has no MASTER predecessor or the query
                does not reference one of them.
        """
        ranges = self.options.calendar.group_contiguous_ranges(
            self.processing_state.get_periods_to_process(),
        )
        source_period_field = self.options.get_source_period_field()
        parsed = sqlglot.parse_one(
            sql_query,
            dialect=dialect,
        )

        for _, master_structure, table_nodes in resolve_master_table_references(
            parsed=parsed,
            predecessors=predecessors,
            input_database_names=input_database_names,
        ):
            column_kind = resolve_column_kind(
                field=master_structure.get_field(source_period_field),
                dialect=dialect,
            )
            for table_node in table_nodes:
                # The condition goes into the SELECT that reads the table,
                # so a MASTER read inside a CTE, a subquery or a UNION
                # branch is filtered where its alias is in scope.
                reading_select = table_node.find_ancestor(exp.Select)
                if reading_select is None:
                    raise ValueError(
                        f"Master predecessor table '{master_structure.name}' "
                        f"is not read by a SELECT of the SQL query."
                    )
                reading_select.where(
                    build_period_condition(
                        column=exp.Column(
                            this=exp.to_identifier(source_period_field),
                            table=exp.to_identifier(
                                get_table_alias_or_name(table_node),
                            ),
                        ),
                        ranges=ranges,
                        column_kind=column_kind,
                        timezone=self.options.period_timezone,
                    ),
                    copy=False,
                )

        return str(parsed.sql(dialect=dialect))
