from pydantic import ConfigDict, Field

from nld.pydantic import NldBaseModel


class AuditTarget(NldBaseModel):
    """The environment and physical location the audit was measured against.

    Records where the figures come from so an audit is reproducible and can be
    compared across environments (dev/stg/prd) and runs.

    Example YAML:
        environment: prd
        connection: postgresql_clh
        connector_type: postgresql
        database: nld_isis_clh
        schema: acquisition_web_hr
        table: raw_web_hr_wttj_jobs
    """

    model_config = ConfigDict(populate_by_name=True)

    environment: str = Field(
        description="Target environment the audit was run against (dev/stg/prd)",
    )
    connection: str | None = Field(
        default=None,
        description="Name of the nld connection used to query the data",
    )
    connector_type: str | None = Field(
        default=None,
        description="Connector type of the target (e.g. postgresql, bigquery)",
    )
    database: str | None = Field(
        default=None,
        description="Database the audited structure lives in",
    )
    schema_: str | None = Field(
        default=None,
        alias="schema",
        description="Schema the audited structure lives in",
    )
    table: str | None = Field(
        default=None,
        description="Physical table or view name that was audited",
    )
