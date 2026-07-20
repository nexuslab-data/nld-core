import datetime
import json
from typing import Any, cast

from pydantic import Field

from nld.connector.base.connector import SQLDataConnector
from nld.deploy.change_file_models import (
    PendingChangeFile,
    directive_outcome_key,
)
from nld.logging.logger import NldLoggable
from nld.pydantic.base_model import NldBaseModel
from nld.utils.datetime_util import get_current_datetime

NLD_DEPLOYMENT_CHANGE_TABLE = "_nld_deployment_change"


class DeploymentChangeRow(NldBaseModel):
    """Applied-log row for one deployment change file.

    Stored in the ``_nld_deployment_change`` metadata table. A
    recorded ``change_id`` is never re-executed on this target; the
    ``content_hash`` detects post-apply edits of the file.
    """

    change_id: str = Field(json_schema_extra={"primary_key": True})
    applied_at: datetime.datetime
    content_hash: str
    deployment_id: str
    directive_outcomes: str | None = None


class DeploymentChangeLogManager(NldLoggable):
    """Manages the deployment change applied-log table."""

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
        """Create the applied-log table if it does not exist."""
        self._model_manager.create_table(
            model_class=DeploymentChangeRow,
            schema_name=metadata_schema,
            table_name=NLD_DEPLOYMENT_CHANGE_TABLE,
            track_timestamps=True,
        )

    def get_applied_hashes(
        self,
        metadata_schema: str,
    ) -> dict[str, str]:
        """Return the content hash of every applied change file, by change_id."""
        models = self._model_manager.read_models(
            model_class=DeploymentChangeRow,
            schema_name=metadata_schema,
            table_name=NLD_DEPLOYMENT_CHANGE_TABLE,
        )
        applied: dict[str, str] = {}
        for model in models:
            row = cast(DeploymentChangeRow, model)
            applied[row.change_id] = row.content_hash
        return applied

    def record_applied(
        self,
        metadata_schema: str,
        record: DeploymentChangeRow,
    ) -> None:
        """Record a change file as applied, exactly once per target."""
        self._model_manager.insert_model(
            model=record,
            schema_name=metadata_schema,
            table_name=NLD_DEPLOYMENT_CHANGE_TABLE,
            track_timestamps=True,
        )

    def record_fully_applied(
        self,
        metadata_schema: str,
        pending_change_files: list[PendingChangeFile],
        directive_outcomes: dict[str, str],
        deployment_id: str,
    ) -> None:
        """Record fully-applied change files in the applied-log.

        A change file is recorded only when every one of its
        directives resolved in this run — a scoped deploy leaves the
        files with out-of-scope directives pending for a later run.
        """
        for pending in pending_change_files:
            outcome_keys = [
                directive_outcome_key(directive=directive)
                for directive in pending.change_file.get_directives()
            ]
            if not all(key in directive_outcomes for key in outcome_keys):
                self.log_info(
                    f"Change file '{pending.change_id}' has directives "
                    "outside this deploy scope — left pending.",
                )
                continue

            outcomes = {key: directive_outcomes[key] for key in outcome_keys}
            self.record_applied(
                metadata_schema=metadata_schema,
                record=DeploymentChangeRow(
                    change_id=pending.change_id,
                    applied_at=get_current_datetime(),
                    content_hash=pending.content_hash,
                    deployment_id=deployment_id,
                    directive_outcomes=json.dumps(outcomes),
                ),
            )
            self.log_info(
                f"Change file '{pending.change_id}' recorded as applied.",
            )
