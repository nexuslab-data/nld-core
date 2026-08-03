from typing import Any

from nld.connector.base import UnavailableConnectionProfileException
from nld.flow.definition.flow_definition import (
    DataFlowDefinition,
    NamespacedDataFlowDefinition,
)
from nld.flow.execution import FlowExecutionInfo
from nld.flow.incremental.models import PlannedStatePolicy
from nld.flow.state.state_backend_connector_resolver import (
    build_state_backend_connector_wrapper,
)
from nld.logging.logger import NldLoggable
from nld.parameters import ExecutionParameter, resolve_runtime_params
from nld.parameters.parser import parse_parameters_from_cli
from nld.task.context import NldExecutionContext
from nld.task.context.request import TaskRequest
from nld.utils import ModuleLoader, resolve_environment_variables

from .data_flow_task import (
    DATA_CONNECTOR_INIT_PARAM_SUFFIX,
    DataFlowTask,
)


def parse_parameters_from_cli_for_data_flow_task(
    data_flow_definition: DataFlowDefinition,
) -> dict[str, Any]:
    """Parse CLI args for the incremental params of the resolved logic.

    The set of CLI flags accepted by a flow depends on the per-flow
    ``incremental`` config in YAML, so resolution must happen on the
    definition rather than on the task class.
    """
    incremental_logic = data_flow_definition.resolve_incremental_logic()
    param_defs = incremental_logic.definition.param_definitions
    return parse_parameters_from_cli(
        [param_def.to_execution_param_definition() for param_def in param_defs]
    )


class DataFlowExecutor(NldLoggable):
    def __init__(
        self,
        namespaced_data_flow_definition: NamespacedDataFlowDefinition,
        execution_name: str | None = None,
        params: dict[str, Any] | None = None,
        extra_args: list[str] | None = None,
        planned_state_policy: str = PlannedStatePolicy.AUTO,
    ):
        """Ensures data flow definition is coherent.

        Validates the data flow definition and initializes the flow execution
        context.
        """
        super().__init__()
        self.namespaced_data_flow_definition = namespaced_data_flow_definition
        self.data_flow_definition = namespaced_data_flow_definition.model
        self.namespace = namespaced_data_flow_definition.namespace
        self.planned_state_policy = planned_state_policy

        # --- Step 1: Initialize NLD Execution Context if not set
        nld_context = NldExecutionContext.get_current()
        if nld_context is None:
            self.task_request = TaskRequest(
                execution_name=(
                    execution_name
                    if execution_name is not None
                    else self.data_flow_definition.name
                ),
                params=params,
                extra_args=extra_args,
            )
            NldExecutionContext(
                self.task_request,
                with_project=True,
            ).set_current()
            self.nld_execution_context = NldExecutionContext.require_current()
        else:
            self.task_request = nld_context.task_request
            self.nld_execution_context = nld_context

        # The global ``--profile-name`` CLI flag, when supplied, wins over
        # any per-connection profile pinned in the flow definition.
        self._cli_profile_name: str | None = self.task_request.get_parameters().get(
            "profile_name",
        )

        # --- Step 2: Check of data flow definition coherence (also loads task module)
        is_valid, error_messages = self.data_flow_definition.check_coherence(
            namespace=self.namespace,
            entity_path=self.nld_execution_context.project.entity_path,
            additional_task_paths=self.nld_execution_context.project.flows_python_additional_paths,
            additional_flow_task_types=self.nld_execution_context.project.flow_config.additional_flow_task_types,
        )
        if not is_valid:
            raise ValueError(
                f"The data flow definition is not coherent. "
                f"Please check the following messages: {'.'.join(error_messages)}"
            )

        # --- Step 2.5: Resolve declared environment variables into the context
        # so flow tasks can read them via execution_context.get_environment_variable
        # instead of os.getenv. A missing required variable fails fast here.
        self.nld_execution_context.set_flow_environment_variables(
            resolve_environment_variables(
                self.data_flow_definition.get_variables(),
            )
        )

        # --- Step 3: Validate runtime parameter types
        self._check_runtime_param_types()

        # --- Step 4: Check the availability of services
        self._check_connectors_availability_in_context(self.data_flow_definition)

    def _get_runtime_params(self) -> list[ExecutionParameter]:
        """Filter runtime parameters from the flow definition."""
        if self.data_flow_definition.params is None:
            return []
        return [param for param in self.data_flow_definition.params if param.runtime]

    def _check_incremental_init_params(self, init_params: dict[str, Any]) -> None:
        """Validate mandatory incremental params from the resolved logic.

        ``BaseTask.check_init_params_dict`` only validates params declared
        on the task class. Incremental params come from the per-flow
        resolver, so they need a separate mandatory-key check here.
        """
        from nld.exceptions import MissingMandatoryArgumentException

        for param_def in self.data_flow_definition.resolve_incremental_logic().definition.param_definitions:  # noqa: E501
            if not param_def.mandatory:
                continue
            if param_def.name in init_params:
                continue
            raise MissingMandatoryArgumentException(
                object_type=type(self),
                method_name="_check_incremental_init_params",
                argument_name=param_def.name,
            )

    def _check_runtime_param_types(self) -> None:
        """Validate that runtime parameter types can be loaded."""
        runtime_params = self._get_runtime_params()
        if not runtime_params:
            return

        additional_paths = (
            self.nld_execution_context.project.flows_python_additional_paths
        )
        loader = ModuleLoader(additional_paths=additional_paths)
        for param in runtime_params:
            if param.type is None or param.type in ("Any", "str"):
                continue
            loader.load_class(
                path_or_class_name=param.type,
                try_to_import_from_additional_paths=bool(additional_paths),
            )

    def init_data_flow_task(
        self,
        connections_should_be_opened: bool = True,
        extra_init_params: dict[str, Any] | None = None,
    ) -> DataFlowTask:
        """
        Initializes the data flow task.

        Args:
            connections_should_be_opened: Flag to indicate if connections
                should be opened. By default is True. Can be useful during
                testing.
            extra_init_params: Init parameters applied last, overriding
                the CLI-derived values — used by programmatic callers
                (e.g. the deploy reload forcing ``full=True``).

        Returns:
            An initialized data flow task.
        """
        # --- Step 1: Get the task class (already loaded by check_coherence)
        task_class = self.data_flow_definition._require_task_class()
        task_type: type[DataFlowTask] = task_class

        # --- Step 2: Load the data connectors
        self._load_data_connectors(
            self.data_flow_definition,
            connections_should_be_opened,
        )

        # --- Step 3: Build the init task parameters
        init_params: dict[str, Any] = {}
        init_params["namespaced_data_flow_definition"] = (
            self.namespaced_data_flow_definition
        )
        init_params["planned_state_policy"] = self.planned_state_policy
        init_params.update(self.data_flow_definition.get_params_model_dict_for_init())
        init_params.update(
            self._get_data_connectors_init_params(self.data_flow_definition)
        )
        cli_parameters = self.task_request.get_parameters()
        init_params.update(
            {
                key: value
                for key, value in cli_parameters.items()
                if key in self.data_flow_definition.get_init_params_keys()
            }
        )
        runtime_params = self._get_runtime_params()
        if runtime_params:
            init_type_hints = task_type.get_init_param_type_hints()
            init_keys = self.data_flow_definition.get_init_params_keys()
            additional_paths = (
                self.nld_execution_context.project.flows_python_additional_paths
            )
            init_params.update(
                {
                    key: value
                    for key, value in resolve_runtime_params(
                        runtime_params=runtime_params,
                        cli_values=cli_parameters,
                        param_type_hints=init_type_hints,
                        additional_paths=additional_paths,
                    ).items()
                    if key in init_keys
                }
            )

        if extra_init_params:
            init_params.update(extra_init_params)

        # --- Step 4: Check the init parameters validity for this task
        task_type.check_init_params_dict(init_params)
        self._check_incremental_init_params(init_params)

        # --- Step 5: Construction of the task (without state manager)
        task_inst = task_type(**init_params)

        # --- Step 6: Initialize state manager after construction
        task_inst.init_state_manager()

        return task_inst

    def execute_data_flow_task(
        self,
        data_flow_task: DataFlowTask,
    ) -> FlowExecutionInfo:
        """Executes the data flow task using the executor run parameters.

        Args:
            data_flow_task: The data flow task to execute.

        Returns:
            The flow execution info.
        """
        # --- Step 1: Build the task run parameters
        run_params = {}
        run_params.update(self.data_flow_definition.get_params_model_dict_for_run())
        cli_parameters = self.task_request.get_parameters()
        run_params.update(
            {
                key: value
                for key, value in cli_parameters.items()
                if key in self.data_flow_definition.get_run_params_keys()
            }
        )
        runtime_params = self._get_runtime_params()
        if runtime_params:
            task_class = self.data_flow_definition._require_task_class()
            run_type_hints = task_class.get_run_param_type_hints()
            run_keys = self.data_flow_definition.get_run_params_keys()
            additional_paths = (
                self.nld_execution_context.project.flows_python_additional_paths
            )
            run_params.update(
                {
                    key: value
                    for key, value in resolve_runtime_params(
                        runtime_params=runtime_params,
                        cli_values=cli_parameters,
                        param_type_hints=run_type_hints,
                        additional_paths=additional_paths,
                    ).items()
                    if key in run_keys
                }
            )

        # --- Step 2: Check the run parameters validity for this task
        data_flow_task.check_run_params_dict(run_params)

        # --- Step 3: Execution of the task
        return data_flow_task.run(**run_params)

    def _check_connectors_availability_in_context(
        self,
        data_flow_definition: DataFlowDefinition,
    ) -> None:
        """Ensure connectors expected are available in the context."""
        if not data_flow_definition.data_connectors:
            self.log_debug("No data connectors needed for the execution of this flow")
            return

        required_service_connections = (
            data_flow_definition.get_connector_connection_names()
        )
        available_service_connections = (
            self.nld_execution_context.connection_configs.get_connection_names()
        )
        # Ensure all required services are in db_services
        for required_service_connection in required_service_connections:
            if not any(
                available_service_connection == required_service_connection
                for available_service_connection in available_service_connections
            ):
                raise ValueError(
                    f"Required connector {required_service_connection} "
                    "not found in data connections."
                )
        self.log_debug("All required connectors are available")

    def _load_data_connectors(
        self,
        data_flow_definition: DataFlowDefinition,
        connections_should_be_opened: bool = True,
    ) -> None:
        """Load all the connectors needed for this data flow definition execution.

        Each flow data connector is opened with its resolved credential
        profile (CLI flag > per-connection definition profile > default).
        The state backend side(s) are opened here too — building the
        wrapper lazy-loads and opens each configured side with the same
        precedence — so their profile is applied at connection load time.
        """
        for connector_name, connector_config in (
            data_flow_definition.data_connectors or {}
        ).items():
            # CLI flag wins over the per-connection definition profile;
            # None falls through to the connection's default profile.
            profile_name = (
                self._cli_profile_name
                if self._cli_profile_name is not None
                else connector_config.profile_name
            )
            try:
                self.nld_execution_context.get_data_connector(
                    connector_config.connector,
                    profile_name=profile_name,
                    open_connection=connections_should_be_opened,
                )
            except UnavailableConnectionProfileException as exc:
                # Name the offending connector so the operator knows which
                # definition entry carries the invalid profile.
                exc.message = f"Connector '{connector_name}': {exc.message}"
                exc.args = (exc.message,)
                raise

        # Opens the configured state backend side(s) with their resolved
        # profile; returns None when no state backend is declared.
        build_state_backend_connector_wrapper(
            namespaced_data_flow_definition=self.namespaced_data_flow_definition,
            execution_context=self.nld_execution_context,
            open_connection=connections_should_be_opened,
            override_profile_name=self._cli_profile_name,
        )

        available_connector_names = (
            self.nld_execution_context.get_available_data_connector_names()
        )
        if available_connector_names:
            connector_names = ", ".join(available_connector_names)
            self.log_debug(f"Connectors loaded: {connector_names}")

    def _get_data_connectors_init_params(
        self,
        data_flow_definition: DataFlowDefinition,
    ) -> dict[str, Any]:
        data_connector_init_param_mapping = data_flow_definition.data_connectors or {}
        data_connectors_init_params: dict[str, Any] = {}
        for key, connector_config in data_connector_init_param_mapping.items():
            connection_name = connector_config.connector
            if (
                connection_name
                in self.nld_execution_context.get_available_data_connector_names()
            ):
                data_connectors_init_params.update(
                    {
                        key + DATA_CONNECTOR_INIT_PARAM_SUFFIX: (
                            self.nld_execution_context.get_data_connector(
                                name=connection_name,
                                open_connection=False,
                            )
                        )
                    }
                )
            else:
                raise Exception(
                    f"Data Connector {key} is not available in the "
                    f"flow execution context but was requested for flow execution"
                )

        state_backend_connector_wrapper = build_state_backend_connector_wrapper(
            namespaced_data_flow_definition=self.namespaced_data_flow_definition,
            execution_context=self.nld_execution_context,
            open_connection=False,
            override_profile_name=self._cli_profile_name,
        )
        if state_backend_connector_wrapper is not None:
            data_connectors_init_params["state_backend_connector_wrapper"] = (
                state_backend_connector_wrapper
            )

        return data_connectors_init_params


def execute_data_flow(
    data_flow_name: str,
    namespace_name: str | None = None,
) -> FlowExecutionInfo:
    # --- Step 1: Get the current NLD execution context
    nld_execution_context = NldExecutionContext.require_current()

    # --- Step 2: Retrieve the data flow from the entity registry
    namespaced_data_flow_definition = (
        nld_execution_context.entity_registry.get_data_flow_definition(
            entity_key=data_flow_name,
            namespace=namespace_name,
        )
    )

    # --- Step 3: Load the task module
    namespaced_data_flow_definition.model.load_task_module(
        namespace=namespaced_data_flow_definition.namespace,
        entity_path=nld_execution_context.project.entity_path,
        additional_task_paths=nld_execution_context.project.flows_python_additional_paths,
        additional_flow_task_types=nld_execution_context.project.flow_config.additional_flow_task_types,
    )
    # --- Step 4: Initialize data flow executor
    executor = DataFlowExecutor(
        namespaced_data_flow_definition=namespaced_data_flow_definition,
        params=parse_parameters_from_cli_for_data_flow_task(
            namespaced_data_flow_definition.model,
        ),
    )
    data_flow_task = executor.init_data_flow_task(connections_should_be_opened=True)

    # --- Step 5: Execute the task
    return executor.execute_data_flow_task(data_flow_task)
