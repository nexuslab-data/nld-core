from typing import Any, ClassVar

from nld.connector.base.connector import SQLDataConnector
from nld.flow.definition import DataFlowDefinition, NamespacedDataFlowDefinition
from nld.flow.incremental.impl.no_increment.logic import (
    NO_INCREMENT_FLOW_INCREMENTAL_LOGIC,
)
from nld.flow.incremental.models import FlowIncrementalLogic
from nld.flow.sql.sql_file_resolver import (
    load_sql_file_content,
    try_resolve_sql_file_path,
)
from nld.flow.sql.sql_glot_utils import build_technical_timestamps_query
from nld.flow.sql.sql_query_resolver import render_sql_from_flow_definition
from nld.flow.task.data_flow_task import DataFlowTask
from nld.flow.utils import FlowStepCategory
from nld.flow.utils.flow_update_strategy import FlowUpdateStrategies
from nld.parameters import ExecutionParameterDefinition
from nld.structure import Structure
from nld.structure.field import FieldCharacterisationDefinitionNames
from nld.task.context.context import NldExecutionContext
from nld.utils import resolve_variables
from nld.utils.datetime_util import get_current_datetime
from nld.utils.jinja_utils import render_template

from .sql_write_strategy import SQLWriteStrategy, get_write_strategy

_TECHNICAL_TIMESTAMP_MAPPING: list[tuple[str, str]] = [
    (
        FieldCharacterisationDefinitionNames.REC_PREVIOUS_LAYER_UPDATE_TST,
        "previous_layer_last_updated_at",
    ),
    (
        FieldCharacterisationDefinitionNames.REC_SOURCE_EXTRACTION_TST,
        "source_extracted_at",
    ),
    (
        FieldCharacterisationDefinitionNames.REC_SOURCE_LAST_UPDATE_TST,
        "source_last_updated_at",
    ),
]


class SQLFlowTask(DataFlowTask):
    """Execute a SQL SELECT query to write data to a target table.

    Resolves the SQL query from a co-located .sql file or, when no
    file exists, auto-renders it from the flow definition's
    target_from_sources_mapping and target structure templates. The
    configured write strategy (OVERWRITE, VIEW, INSERT, UPSERT,
    DELETE_INSERT, or UPSERT_LOGICAL_DELETE) is then applied on the
    target connector.

    When the flow definition declares an ``incremental`` strategy, the
    incremental logic is resolved dynamically and the SQL query is
    automatically filtered based on the loading strategy.
    """

    _INCREMENTAL_LOGIC: ClassVar[FlowIncrementalLogic[Any] | None] = (
        NO_INCREMENT_FLOW_INCREMENTAL_LOGIC
    )

    init_params = [
        ExecutionParameterDefinition(
            name="namespaced_data_flow_definition",
            mandatory=True,
        ),
        ExecutionParameterDefinition(name="target_connector", mandatory=True),
        ExecutionParameterDefinition(name="target_schema", mandatory=False),
    ]

    def __init__(
        self,
        target_connector: SQLDataConnector[Any],
        target_schema: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.namespaced_data_flow_definition: NamespacedDataFlowDefinition
        self.data_flow_definition: DataFlowDefinition
        self.target_connector = target_connector
        self.target_schema = self._resolve_target_schema(target_schema)

    def run_flow(self) -> None:
        """Execute the SQL flow using the configured write strategy."""
        self.target_connector.assert_connection_is_opened()

        for statements, variables in self._resolve_all_hooks(hook_type="pre"):
            self._execute_hook_statements(
                statements=statements,
                hook_label="PRE_HOOK",
                step_category=FlowStepCategory.PRE_HOOK,
                template_variables=variables,
            )

        write_strategy_name = self.data_flow_definition.write_strategy or "OVERWRITE"

        sql_query = self._resolve_sql_query()
        sql_query = self._apply_incremental_filter(sql_query)
        table_path = f"{self.target_schema}.{self.data_flow_definition.name}"

        write_strategy = get_write_strategy(write_strategy_name)
        self._assert_strategy_incremental_compatible(write_strategy)
        target_structure = self._resolve_target_structure(write_strategy)

        self.log_info(
            f"Write strategy: {write_strategy.name} | target: {table_path}",
        )

        query_results = write_strategy.execute(
            connector=self.target_connector,
            table_path=table_path,
            sql_query=sql_query,
            target_structure=target_structure,
        )

        self._append_steps_from_results(
            query_results=query_results,
            strategy_name=write_strategy.name,
            step_category=FlowStepCategory.FLOW_EXECUTION,
        )

        failed_result = next(
            (r for r in query_results if r.failed()),
            None,
        )
        if failed_result is not None:
            raise RuntimeError(
                f"SQL flow failed for {table_path}: {failed_result.get_error_message()}"
            )

        self._load_technical_timestamps(
            target_structure=target_structure,
            table_path=table_path,
        )

        for statements, variables in self._resolve_all_hooks(hook_type="post"):
            self._execute_hook_statements(
                statements=statements,
                hook_label="POST_HOOK",
                step_category=FlowStepCategory.POST_HOOK,
                template_variables=variables,
            )

    def _assert_strategy_incremental_compatible(
        self,
        write_strategy: SQLWriteStrategy,
    ) -> None:
        """Reject strategies whose semantics break under a filtered source.

        UPSERT_LOGICAL_DELETE flags every target row absent from the
        source query as deleted: an incrementally filtered (delta) source
        would mass-flag all untouched rows. The check runs even when the
        filter would no-op (no predecessors) — declaring ``incremental``
        on such a flow is a configuration error either way.
        """
        if write_strategy.name != FlowUpdateStrategies.UPSERT_LOG_DEL:
            return
        if self.data_flow_definition.incremental is None:
            return
        raise ValueError(
            f"Write strategy '{write_strategy.name}' requires the full "
            f"source extent and cannot be combined with an incremental "
            f"configuration on flow '{self.data_flow_definition.name}'"
        )

    def _apply_incremental_filter(self, sql_query: str) -> str:
        """Apply incremental WHERE clause filtering to the SQL query.

        Delegates to the incremental state manager's apply_sql_filter
        method. Returns the query unmodified when no filtering is
        applicable.

        Uses the target connector's sqlglot dialect rather than a
        hardcoded one so user SQL with dialect-specific syntax
        (e.g. BigQuery raw string literals ``r'...'``, Snowflake
        identifier quoting) is parsed correctly.
        """
        flow_definition = self.data_flow_definition
        if flow_definition is None or flow_definition.incremental is None:
            return sql_query

        if not flow_definition.predecessors:
            return sql_query

        incremental_manager = self.state_manager.incremental_state_manager
        dialect = getattr(self.target_connector, "sqlglot_dialect", None) or "postgres"
        return incremental_manager.apply_sql_filter(
            sql_query=sql_query,
            predecessors=flow_definition.predecessors,
            dialect=dialect,
        )

    def _load_technical_timestamps(
        self,
        target_structure: Structure | None,
        table_path: str,
    ) -> None:
        """Query the target table to populate technical timestamp metadata.

        Reads MAX values of characterised timestamp fields from the
        loaded data (filtered by REC_LAST_UPDATE_TST >= started_at)
        and sets them on the flow execution info.
        """
        if target_structure is None:
            return

        filter_field_name = target_structure.get_field_name_with_characterisation(
            FieldCharacterisationDefinitionNames.REC_LAST_UPDATE_TST,
        )
        if filter_field_name is None:
            return

        timestamp_fields = self._resolve_technical_timestamp_fields(target_structure)
        if not timestamp_fields:
            return

        try:
            query = build_technical_timestamps_query(
                table_path=table_path,
                filter_field_name=filter_field_name,
                timestamp_fields=timestamp_fields,
                started_at=self.flow_execution_info.started_at,
                completed_at=get_current_datetime(),
                dialect=self.target_connector.sqlglot_dialect,
            )

            query_result = self.target_connector.execute_query(query)

            self._append_steps_from_results(
                query_results=[query_result],
                strategy_name="TECHNICAL_METADATA",
                step_category=FlowStepCategory.TECHNICAL_METADATA,
            )

            if query_result.failed():
                self.log_warn(
                    "Technical metadata query failed: "
                    f"{query_result.get_error_message()}",
                )
                return

            result_dict = query_result.get_result_dict()
            if not result_dict:
                return

            for _, exec_info_field, alias in timestamp_fields:
                value = result_dict.get(alias)
                if value is not None:
                    setattr(
                        self.flow_execution_info,
                        exec_info_field,
                        value,
                    )

        except Exception as ex:
            self.log_warn(
                f"Failed to load technical timestamps: {ex}",
            )

    @staticmethod
    def _resolve_technical_timestamp_fields(
        target_structure: Structure,
    ) -> list[tuple[str, str, str]]:
        """Resolve which technical timestamp fields exist on the structure.

        Returns a list of (column_name, exec_info_field, alias) tuples.
        """
        fields: list[tuple[str, str, str]] = []
        for characterisation, exec_info_field in _TECHNICAL_TIMESTAMP_MAPPING:
            column_name = target_structure.get_field_name_with_characterisation(
                characterisation,
            )
            if column_name is not None:
                fields.append((column_name, exec_info_field, exec_info_field))
        return fields

    def _build_hook_template_variables(self) -> dict[str, str]:
        """Build the Jinja template variables available in flow-level hooks.

        Custom hook variables (from project config and env vars) are
        included but cannot shadow built-in variables.
        """
        context = NldExecutionContext.require_current()
        custom_variables = resolve_variables(
            project_variables=context.project.variables,
        )
        target_structure_name = self.data_flow_definition.name
        return {
            **custom_variables,
            "target_schema": self.target_schema,
            "target_structure_name": target_structure_name,
            "target_object_path": f"{self.target_schema}.{target_structure_name}",
        }

    def _build_structure_hook_template_variables(self) -> dict[str, str]:
        """Build the Jinja template variables available in structure-level hooks.

        Custom hook variables (from project config and env vars) are
        included but cannot shadow built-in variables.
        """
        context = NldExecutionContext.require_current()
        custom_variables = resolve_variables(
            project_variables=context.project.variables,
        )
        structure_name = self.data_flow_definition.name
        return {
            **custom_variables,
            "schema": self.target_schema,
            "structure_name": structure_name,
            "object_path": f"{self.target_schema}.{structure_name}",
        }

    def _resolve_all_hooks(
        self,
        hook_type: str,
    ) -> list[tuple[list[str], dict[str, str]]]:
        """Resolve all hook statements from structure and flow levels.

        Structure-level hooks execute first, then flow-level hooks.
        Each hook type (pre/post) is resolved independently.

        Args:
            hook_type: Either "pre" or "post".

        Returns:
            A list of (statements, template_variables) tuples.
        """
        result: list[tuple[list[str], dict[str, str]]] = []

        if self.data_flow_definition.target_structure is not None:
            target_structure = self.data_flow_definition.resolve_target_structure()
            if target_structure.is_view():
                hook_getter = getattr(
                    target_structure,
                    f"get_all_{hook_type}_deployment_sql_hooks",
                )
                structure_hooks = hook_getter()
                if structure_hooks:
                    result.append(
                        (
                            structure_hooks,
                            self._build_structure_hook_template_variables(),
                        ),
                    )

        sql_config = self.data_flow_definition.sql
        flow_hooks = (
            getattr(
                sql_config,
                f"{hook_type}_hook",
                None,
            )
            if sql_config
            else None
        )
        if flow_hooks:
            result.append(
                (flow_hooks, self._build_hook_template_variables()),
            )

        return result

    def _execute_hook_statements(
        self,
        statements: list[str] | None,
        hook_label: str,
        step_category: str,
        template_variables: dict[str, str] | None = None,
    ) -> None:
        """Execute a list of SQL hook statements sequentially.

        Each statement is executed on the target connector and tracked
        as an individual step. Execution stops on the first failure.
        Jinja template variables are rendered before execution.
        """
        if not statements:
            return

        self.log_info(f"Executing {hook_label} ({len(statements)} statement(s))")

        for index, sql_statement in enumerate(statements):
            if template_variables:
                sql_statement = render_template(
                    sql_statement,
                    **template_variables,
                )
            statement_number = index + 1
            query_result = self.target_connector.execute_query(sql_statement)

            self._append_steps_from_results(
                query_results=[query_result],
                strategy_name=f"{hook_label} - Statement {statement_number}",
                step_category=step_category,
            )

            if query_result.failed():
                raise RuntimeError(
                    f"{hook_label} statement {statement_number} failed: "
                    f"{query_result.get_error_message()}"
                )

    def _resolve_target_structure(
        self,
        write_strategy: SQLWriteStrategy,
    ) -> Structure | None:
        """Resolve the target structure when required by the strategy."""
        if not write_strategy.requires_target_structure:
            return None

        flow_definition = self.data_flow_definition
        if flow_definition.target_structure is None:
            raise ValueError(
                f"Strategy '{write_strategy.name}' requires a "
                f"target_structure on the flow definition "
                f"'{flow_definition.name}'"
            )
        return flow_definition.resolve_target_structure()

    def _resolve_target_schema(self, target_schema: str | None) -> str:
        """Resolve the target schema from parameter or connector credentials."""
        if target_schema is not None:
            return target_schema

        credentials = self.target_connector.connection_wrapper.credentials
        connector_schema: str | None = getattr(credentials, "schema_name", None)
        if connector_schema is not None:
            return connector_schema

        # BigQuery credentials historically use ``dataset_id`` as the
        # schema name. Fall back to it so a connection configured with
        # only ``dataset_id`` works in SQL flows, matching what the
        # connector and backend mixin already do.
        dataset_id: str | None = getattr(credentials, "dataset_id", None)
        if dataset_id is not None:
            return dataset_id

        raise ValueError(
            "No target_schema specified and the connector credentials "
            "do not provide a schema_name."
        )

    def _resolve_sql_query(self) -> str:
        """Resolve the SQL query from file or auto-rendering.

        Tries the .sql file first. When absent, falls back to
        rendering from flow metadata when target_from_sources_mapping
        is defined on the flow definition.
        """
        context = NldExecutionContext.require_current()
        sql_file_path = try_resolve_sql_file_path(
            entities_root_folder_path=context.project.entities_root_folder_path,
            namespace=self.namespaced_data_flow_definition.namespace,
            flow_name=self.data_flow_definition.name,
        )
        if sql_file_path is not None:
            return load_sql_file_content(sql_file_path)

        if self.data_flow_definition.target_from_sources_mapping is not None:
            self.log_info(
                "No .sql file found, auto-rendering from flow metadata",
            )
            return render_sql_from_flow_definition(self.data_flow_definition)

        raise FileNotFoundError(
            f"No .sql file found and no target_from_sources_mapping "
            f"defined for flow '{self.data_flow_definition.name}'. "
            f"Either provide a .sql file or define "
            f"target_from_sources_mapping in the flow definition."
        )
