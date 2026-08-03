from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.scheduling.services import SchedulingValidator
from nld.service import EntityTypeNames
from nld.task.base import StandardTask


class SchedulingValidateTask(StandardTask):
    """Validate the scheduling graph of a single environment.

    Resolves every flow reference and asserts the environment's trigger graph
    is acyclic, raising on the first problem. The environment is resolved with
    the precedence ``--env`` -> ``NLD__ENVIRONMENT`` -> ``environments.default``.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="environment",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        environment: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.environment = environment
        self.execution_context.load_entities(
            entity_types=[
                EntityTypeNames.DATA_FLOW_DEFINITION,
                EntityTypeNames.FLOW_TASK,
            ],
        )

    def run(self, **kwargs: Any) -> bool:
        """Resolve and validate the environment's scheduling graph."""
        environment = self.execution_context.project.environments.resolve_name(
            requested=self.environment,
        )
        graph = SchedulingValidator(
            environment=environment,
            registry=self.execution_context.entity_registry,
        ).validate()

        self.log_info(
            f"Scheduling for environment '{environment}' is valid: "
            f"{len(graph.node_ids)} scheduled task(s), no cycles."
        )
        return True
