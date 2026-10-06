from typing import Any, ClassVar, cast

from nld.connector.base.connector import SQLDataConnector
from nld.deploy.deployment_lock_manager import (
    DeploymentLockManager,
    DeploymentLockRow,
)
from nld.exceptions import NldRuntimeException
from nld.parameters.execution_params_def import ExecutionParameterDefinition
from nld.task.base import StandardTask


class DeployUnlockTask(StandardTask):
    """``nld deploy unlock`` — list or release deploy locks.

    A deploy holds a lock on every target it changes and releases it when
    it ends, even on failure. Only a deploy killed outright (an evicted
    pod, a lost machine) leaves its lock behind; the next deploy of the
    same target then refuses and names this command. Without ``--target``
    the current locks are listed and nothing is released.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="target",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        target: tuple[str, ...] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._targets = list(target or ())

    def run(self, **kwargs: Any) -> list[DeploymentLockRow]:
        """List the locks, or release the ones on the given targets."""
        metadata_connector, metadata_schema = self._resolve_metadata_backend()
        lock_manager = DeploymentLockManager(connector=metadata_connector)
        lock_manager.ensure_table(metadata_schema=metadata_schema)

        if not self._targets:
            locks = lock_manager.get_locks(metadata_schema=metadata_schema)
            self.log_info(f"Deploy locks: {len(locks)}")
            for lock in locks:
                self._log_lock(lock=lock)
            return locks

        released = lock_manager.release_targets(
            metadata_schema=metadata_schema,
            lock_keys=self._targets,
        )
        self.log_info(f"Released {len(released)} deploy lock claim(s)")
        for lock in released:
            self._log_lock(lock=lock)
        return released

    def _log_lock(self, lock: DeploymentLockRow) -> None:
        self.log_info(
            f"  - {lock.lock_key}: deployment {lock.holder_id} "
            f"({lock.command} of {lock.scope}) since {lock.acquired_at}",
        )

    def _resolve_metadata_backend(self) -> tuple[SQLDataConnector[Any], str]:
        """Return the metadata backend connector and the schema holding the locks."""
        connection_name = self.execution_context.project.metadata_backend_connector
        if connection_name is None:
            raise NldRuntimeException(
                "metadata_backend_connector must be set in the project "
                "configuration: deploy locks live on the metadata backend.",
            )
        metadata_connector = cast(
            SQLDataConnector[Any],
            self.execution_context.get_data_connector(
                connection_name,
                open_connection=True,
            ),
        )
        metadata_schema = metadata_connector.get_active_schema()
        if metadata_schema is None:
            raise NldRuntimeException(
                "metadata_backend_connector must have a schema configured. "
                "Set 'schema_name' on the connection credentials.",
            )
        return metadata_connector, metadata_schema
