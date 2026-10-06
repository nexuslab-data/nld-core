import datetime
import json
from typing import Any, cast

from pydantic import Field

from nld.connector.base.connector import SQLDataConnector
from nld.deploy.change_file_models import (
    AppliedChangeDirectives,
    PendingChangeFile,
    directive_outcome_key,
)
from nld.logging.logger import NldLoggable
from nld.pydantic.base_model import NldBaseModel
from nld.utils.datetime_util import get_current_datetime

NLD_DEPLOYMENT_CHANGE_TABLE = "_nld_deployment_change"
NLD_DEPLOYMENT_CHANGE_DIRECTIVE_TABLE = "_nld_deployment_change_directive"


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


class DeploymentChangeDirectiveRow(NldBaseModel):
    """Applied-log row for one directive of a still incomplete change file.

    Stored in the ``_nld_deployment_change_directive`` metadata table. A
    change file can be applied over several namespace deploys: the
    directives resolved while other directives of the file remain pending
    are recorded here, never re-executed on this target, and the file
    joins ``_nld_deployment_change`` once the last of them is resolved.
    """

    change_id: str = Field(json_schema_extra={"primary_key": True})
    outcome_key: str = Field(json_schema_extra={"primary_key": True})
    applied_at: datetime.datetime
    content_hash: str
    deployment_id: str
    outcome: str


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
        """Create the file and directive applied-log tables if they do not exist."""
        self._model_manager.create_table(
            model_class=DeploymentChangeRow,
            schema_name=metadata_schema,
            table_name=NLD_DEPLOYMENT_CHANGE_TABLE,
            track_timestamps=True,
        )
        self._model_manager.create_table(
            model_class=DeploymentChangeDirectiveRow,
            schema_name=metadata_schema,
            table_name=NLD_DEPLOYMENT_CHANGE_DIRECTIVE_TABLE,
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

    def get_applied_directives(
        self,
        metadata_schema: str,
    ) -> dict[str, AppliedChangeDirectives]:
        """Return the directives applied so far, by change_id.

        Covers the files not yet fully applied as well: they are the ones
        whose remaining directives belong to another deploy scope.
        """
        models = self._model_manager.read_models(
            model_class=DeploymentChangeDirectiveRow,
            schema_name=metadata_schema,
            table_name=NLD_DEPLOYMENT_CHANGE_DIRECTIVE_TABLE,
        )
        applied: dict[str, AppliedChangeDirectives] = {}
        for model in models:
            row = cast(DeploymentChangeDirectiveRow, model)
            applied_directives = applied.setdefault(
                row.change_id,
                AppliedChangeDirectives(content_hash=row.content_hash),
            )
            applied_directives.outcomes[row.outcome_key] = row.outcome
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

    def record_applied_directives(
        self,
        metadata_schema: str,
        pending_change_files: list[PendingChangeFile],
        directive_outcomes: dict[str, str],
        deployment_id: str,
    ) -> None:
        """Record the directives resolved by a deploy, completing the files they finish.

        A change file whose every directive is now resolved — by this run
        or by the earlier deploys of other scopes — is recorded as applied
        with all its outcomes, in one row: a failing write then leaves this
        run's directives unrecorded, and the retry applies them again (the
        exactly-once guarantee covers recorded runs, not the crash window).
        The directives of a file still incomplete are recorded one by one,
        so the deploy of another scope never applies them again.
        """
        applied_at = get_current_datetime()
        for pending in pending_change_files:
            outcome_keys = [
                directive_outcome_key(directive=directive)
                for directive in pending.change_file.get_directives()
            ]
            new_outcomes = {
                key: directive_outcomes[key]
                for key in outcome_keys
                if key in directive_outcomes
                and key not in pending.applied_directive_outcomes
            }
            outcomes = {**pending.applied_directive_outcomes, **new_outcomes}
            left_pending = [key for key in outcome_keys if key not in outcomes]
            if not left_pending:
                self.record_applied(
                    metadata_schema=metadata_schema,
                    record=DeploymentChangeRow(
                        change_id=pending.change_id,
                        applied_at=applied_at,
                        content_hash=pending.content_hash,
                        deployment_id=deployment_id,
                        directive_outcomes=json.dumps(
                            {key: outcomes[key] for key in outcome_keys},
                        ),
                    ),
                )
                self.log_info(
                    f"Change file '{pending.change_id}' recorded as applied.",
                )
                continue

            for outcome_key, outcome in new_outcomes.items():
                self._model_manager.insert_model(
                    model=DeploymentChangeDirectiveRow(
                        change_id=pending.change_id,
                        outcome_key=outcome_key,
                        applied_at=applied_at,
                        content_hash=pending.content_hash,
                        deployment_id=deployment_id,
                        outcome=outcome,
                    ),
                    schema_name=metadata_schema,
                    table_name=NLD_DEPLOYMENT_CHANGE_DIRECTIVE_TABLE,
                    track_timestamps=True,
                )
            self.log_info(
                f"Change file '{pending.change_id}' has "
                f"{len(left_pending)} directive(s) outside this deploy "
                "scope — left pending.",
            )
