from typing import Any, ClassVar

from nld.connector.base.connector import SQLDataConnector
from nld.flow.definition import DataFlowDefinition, NamespacedDataFlowDefinition
from nld.flow.incremental.impl.no_increment.logic import (
    NO_INCREMENT_FLOW_INCREMENTAL_LOGIC,
)
from nld.flow.incremental.models import FlowIncrementalLogic
from nld.flow.quality import DataQualityContext
from nld.flow.seed.seed_file_resolver import resolve_seed_file_path
from nld.flow.seed.seed_write_strategy import get_seed_write_strategy
from nld.flow.task.data_flow_task import DataFlowTask
from nld.flow.utils import FlowStepCategory
from nld.parameters import ExecutionParameterDefinition
from nld.structure import Structure
from nld.task.context.context import NldExecutionContext


class SeedFlowTask(DataFlowTask):
    """Load a CSV seed file into a target SQL table.

    Reads a CSV file from the project seeds folder and applies the
    configured write strategy (OVERWRITE, INSERT, or UPSERT) on the
    target connector using DML-only operations. The target table must
    already exist (created via ``nld structure deploy``).

    The CSV file path is resolved from the target_structure reference
    on the flow definition. For example, a target_structure of
    "reference.country_codes" resolves to:
        <entities_root>/seeds/reference/country_codes.csv

    CSV column names are validated against the target structure fields
    before any rows are written.

    Seed flows always reload the whole CSV file, so an ``incremental``
    config other than ``no_increment`` is rejected at initialisation.
    """

    _INCREMENTAL_LOGIC: ClassVar[FlowIncrementalLogic[Any]] = (
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
        self._assert_no_incremental()
        self.target_connector = target_connector
        self.target_schema = self._resolve_target_schema(target_schema)

    def run_flow(self) -> None:
        """Execute the seed flow using the configured write strategy."""
        self.target_connector.assert_connection_is_opened()
        self._assert_no_overwrite_replace()

        write_strategy_name = self.data_flow_definition.write_strategy or "OVERWRITE"
        write_strategy = get_seed_write_strategy(
            strategy_name=write_strategy_name,
            connector=self.target_connector,
        )

        target_structure = self._resolve_required_target_structure()
        seed_file_path = self._resolve_seed_file_path()
        table_path = f"{self.target_schema}.{self.data_flow_definition.name}"

        self.log_info(
            f"Executing seed flow for table: {table_path} "
            f"with strategy: {write_strategy.name}"
        )

        query_results = write_strategy.execute(
            connector=self.target_connector,
            table_path=table_path,
            seed_file_path=seed_file_path,
            target_structure=target_structure,
        )

        self._append_steps_from_results(
            query_results=query_results,
            strategy_name=write_strategy.name,
            step_category=FlowStepCategory.FLOW_EXECUTION,
        )

        failed_result = next(
            (result for result in query_results if result.failed()),
            None,
        )
        if failed_result is not None:
            raise RuntimeError(
                f"Seed flow failed for {table_path}: "
                f"{failed_result.get_error_message()}"
            )

        self.log_info(
            f"Seed flow completed successfully for table: {table_path}, "
            f"{len(query_results)} queries executed"
        )

    def _assert_no_incremental(self) -> None:
        """Reject delta incremental types, seed flows reload the whole file.

        The base task resolves the incremental logic from the flow config
        first, so without this check a seed flow would track a delta state
        while still loading every row of its CSV file.
        """
        incremental_config = self.incremental_config
        no_increment_type = self._INCREMENTAL_LOGIC.definition.category
        if (
            incremental_config is not None
            and incremental_config.type != no_increment_type
        ):
            raise ValueError(
                f"Incremental type '{incremental_config.type}' is not supported "
                f"by seed flows (flow '{self.data_flow_definition.name}'); seed "
                f"flows always reload the whole CSV file, remove 'incremental' "
                f"or set it to '{no_increment_type}'"
            )

    def _assert_no_overwrite_replace(self) -> None:
        """Reject the replace OVERWRITE mode, which only SQL flows implement."""
        options = self.data_flow_definition.write_strategy_options
        if options is not None and options.is_overwrite_replace():
            raise ValueError(
                f"'write_strategy_options.overwrite_mode: replace' is not "
                f"supported by seed flows (flow "
                f"'{self.data_flow_definition.name}'); seed flows always "
                f"overwrite with TRUNCATE + INSERT"
            )

    def get_data_quality_context(self) -> DataQualityContext | None:
        """Build the quality context from the resolved seed target."""
        return self._build_sql_target_data_quality_context(
            connector=self.target_connector,
            target_schema=self.target_schema,
        )

    def _resolve_target_schema(self, target_schema: str | None) -> str:
        """Resolve the target schema from parameter or connector credentials."""
        if target_schema is not None:
            return target_schema

        connector_schema: str | None = getattr(
            self.target_connector.connection_wrapper.credentials,
            "schema_name",
            None,
        )
        if connector_schema is not None:
            return connector_schema

        raise ValueError(
            "No target_schema specified and the connector credentials "
            "do not provide a schema_name."
        )

    def _resolve_required_target_structure(self) -> Structure:
        """Resolve the target structure, raising when absent.

        Seed flows always require a target_structure because the CSV
        path and column validation depend on it.
        """
        flow_definition = self.data_flow_definition
        if flow_definition.target_structure is None:
            raise ValueError(
                f"SeedFlowTask requires a target_structure on the flow "
                f"definition '{flow_definition.name}'"
            )
        return flow_definition.resolve_target_structure()

    def _resolve_seed_file_path(self) -> str:
        """Resolve the CSV seed file path from the target_structure reference."""
        context = NldExecutionContext.require_current()
        flow_definition = self.data_flow_definition

        seed_reference = flow_definition.target_structure
        if seed_reference is None:
            raise ValueError(
                f"SeedFlowTask requires a target_structure on the flow "
                f"definition '{flow_definition.name}'"
            )
        seed_namespace = str(seed_reference.namespace)
        seed_name = seed_reference.entity_name

        return resolve_seed_file_path(
            entities_root_folder_path=context.project.entities_root_folder_path,
            namespace=seed_namespace,
            seed_name=seed_name,
            entity_layout=context.project.entity_layout,
        )
