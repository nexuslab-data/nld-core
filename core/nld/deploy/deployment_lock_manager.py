import datetime
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, cast

from pydantic import Field

from nld.connector.base.connector import SQLDataConnector
from nld.exceptions import NldRuntimeException
from nld.logging.logger import NldLoggable
from nld.pydantic.base_model import NldBaseModel
from nld.utils.datetime_util import get_current_datetime

NLD_DEPLOYMENT_LOCK_TABLE = "_nld_deployment_lock"


class DeploymentLockedError(NldRuntimeException):
    """Raised when another deploy holds a lock on a target this deploy needs."""


class DeploymentLockRow(NldBaseModel):
    """One deploy's claim on one deploy target.

    Stored in the ``_nld_deployment_lock`` metadata table. Every deploy
    inserts its own row per target, so the table holds the contenders of
    a target rather than a single owner: the earliest claim holds the
    lock. This works on engines that do not enforce primary keys
    (BigQuery, Snowflake), where an insert conflict cannot be relied on.
    """

    lock_key: str = Field(json_schema_extra={"primary_key": True})
    holder_id: str = Field(json_schema_extra={"primary_key": True})
    acquired_at: datetime.datetime
    command: str
    scope: str


class DeploymentLockManager(NldLoggable):
    """Serializes the deploys that change the same deploy targets.

    A lock key names one target (``<connection>:<schema>``): two deploys
    touching a common target run one after the other, while deploys of
    distinct targets — two namespaces mapped to their own schemas — run
    concurrently. A lock is held while a change set is applied only;
    planning and previews never take one.
    """

    def __init__(
        self,
        connector: SQLDataConnector[Any],
    ) -> None:
        super().__init__()
        self._connector = connector
        self._model_manager = connector.get_model_manager()

    def ensure_table(
        self,
        metadata_schema: str,
    ) -> None:
        """Create the lock table if it does not exist."""
        self._model_manager.create_table(
            model_class=DeploymentLockRow,
            schema_name=metadata_schema,
            table_name=NLD_DEPLOYMENT_LOCK_TABLE,
        )

    def get_locks(
        self,
        metadata_schema: str,
    ) -> list[DeploymentLockRow]:
        """Return every claim currently recorded, holders and waiters alike."""
        models = self._model_manager.read_models(
            model_class=DeploymentLockRow,
            schema_name=metadata_schema,
            table_name=NLD_DEPLOYMENT_LOCK_TABLE,
        )
        return [cast(DeploymentLockRow, model) for model in models]

    def acquire(
        self,
        metadata_schema: str,
        lock_keys: list[str],
        holder_id: str,
        command: str,
        scope: str,
    ) -> None:
        """Claim every lock key, or release them all and raise.

        The claims are inserted first, then read back: a key is held by
        its earliest claim (ties broken by holder id), so of two deploys
        racing for a target exactly one sees itself first.
        """
        if not lock_keys:
            return
        acquired_at = get_current_datetime()
        for lock_key in sorted(set(lock_keys)):
            self._model_manager.insert_model(
                model=DeploymentLockRow(
                    lock_key=lock_key,
                    holder_id=holder_id,
                    acquired_at=acquired_at,
                    command=command,
                    scope=scope,
                ),
                schema_name=metadata_schema,
                table_name=NLD_DEPLOYMENT_LOCK_TABLE,
            )

        holders = self._find_holders(
            locks=self.get_locks(metadata_schema=metadata_schema),
            lock_keys=lock_keys,
        )
        blocking = [
            holder for holder in holders.values() if holder.holder_id != holder_id
        ]
        if not blocking:
            return

        self.release(
            metadata_schema=metadata_schema,
            holder_id=holder_id,
        )
        details = "; ".join(
            f"'{holder.lock_key}' by deployment {holder.holder_id} "
            f"({holder.command} of {holder.scope}) since {holder.acquired_at}"
            for holder in blocking
        )
        unlock_targets = " ".join(f"--target {holder.lock_key}" for holder in blocking)
        raise DeploymentLockedError(
            f"Another deploy is changing the same target(s): {details}. "
            "Wait for it to finish; if it is no longer running, release its "
            f"lock with: nld deploy unlock {unlock_targets}",
        )

    def release(
        self,
        metadata_schema: str,
        holder_id: str,
    ) -> None:
        """Remove every claim of one deploy."""
        self._connector.delete_from(
            table_path=f"{metadata_schema}.{NLD_DEPLOYMENT_LOCK_TABLE}",
            where_conditions={"holder_id": holder_id},
        )

    def release_targets(
        self,
        metadata_schema: str,
        lock_keys: list[str],
    ) -> list[DeploymentLockRow]:
        """Remove every claim on the given targets and return the removed claims.

        The escape hatch for a deploy that died without releasing its
        lock: the claims of every deploy on those targets are dropped.
        """
        released = [
            lock
            for lock in self.get_locks(metadata_schema=metadata_schema)
            if lock.lock_key in lock_keys
        ]
        for lock_key in sorted(set(lock_keys)):
            self._connector.delete_from(
                table_path=f"{metadata_schema}.{NLD_DEPLOYMENT_LOCK_TABLE}",
                where_conditions={"lock_key": lock_key},
            )
        return released

    @contextmanager
    def hold(
        self,
        metadata_schema: str,
        lock_keys: list[str],
        holder_id: str,
        command: str,
        scope: str,
    ) -> Generator[None, Any, None]:
        """Hold the lock keys for the duration of the block.

        Example:
            >>> with lock_manager.hold(metadata_schema="meta", lock_keys=keys,
            ...         holder_id=deployment_id, command="flow deploy",
            ...         scope="namespace 'sales'"):
            ...     apply_the_change_set()
        """
        if not lock_keys:
            yield
            return
        self.ensure_table(metadata_schema=metadata_schema)
        self.acquire(
            metadata_schema=metadata_schema,
            lock_keys=lock_keys,
            holder_id=holder_id,
            command=command,
            scope=scope,
        )
        try:
            yield
        finally:
            self.release(
                metadata_schema=metadata_schema,
                holder_id=holder_id,
            )

    @staticmethod
    def _find_holders(
        locks: list[DeploymentLockRow],
        lock_keys: list[str],
    ) -> dict[str, DeploymentLockRow]:
        """Return the claim holding each lock key: the earliest one."""
        holders: dict[str, DeploymentLockRow] = {}
        for lock in sorted(
            locks,
            key=lambda lock: (lock.acquired_at, lock.holder_id),
        ):
            if lock.lock_key in lock_keys and lock.lock_key not in holders:
                holders[lock.lock_key] = lock
        return holders
