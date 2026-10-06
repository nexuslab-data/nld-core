import os
from typing import Any, ClassVar, cast

from nld.connector.base import ColumnProfileSpec, SQLDataConnector, TableProfile
from nld.parameters import ExecutionParameterDefinition
from nld.pydantic import NldEntityReference
from nld.service import EntityTypeNames, FileOutputService
from nld.structure.audit import (
    AuditColumn,
    AuditColumnCoverage,
    AuditDateCoverage,
    AuditDistribution,
    AuditDistributionValue,
    AuditMetadata,
    AuditSampling,
    AuditTarget,
    StructureAudit,
)
from nld.structure.field import Field, FieldCharacterisationDefinitionNames
from nld.task.base import StandardTask
from nld.utils.datetime_util import (
    get_current_datetime,
    get_current_datetime_as_version_str,
)

AUDIT_INTERNAL_FOLDER = "audits/structure"
MIN_REPRESENTATIVE_ROWS = 100

# Template-managed tracking columns are never structure fields, but guard against
# a structure that inlines them so they never leak into the audited coverage.
_TRACKING_EXACT_NAMES = frozenset(
    {"ts_prv_layer_updated_at", "ts_inserted_at", "ts_updated_at"}
)
_TRACKING_NAME_PREFIXES = ("ts_src_", "rec_")


class StructureAuditRunTask(StandardTask):
    """Profile a structure's physical table and write a StructureAudit YAML.

    This task only *orchestrates*: it resolves the structure and its connection
    from the loaded project, decides which business columns to measure (template
    tracking columns are excluded so the audit validates against the structure),
    then asks the connector's data profiler to measure the table and maps the
    returned :class:`TableProfile` onto a ``StructureAudit`` entity written under
    ``assets/audits/structure/<namespace>/<structure>.yml``.

    The query creation and execution live in the connector layer
    (``connector.get_data_profiler()`` + the engine's sqlglot DML builder), so
    profiling is engine-specific and only available for connectors whose engine
    supports it.

    With ``--sample N`` the figures are computed on a random sample of at most N
    rows and recorded under ``metadata.sampling``. An existing audit is never
    overwritten unless ``--force`` is passed; ``--new-version`` instead writes a
    timestamped audit (``<name>.<YYYYMMDDThhmmss>.yml``) next to the canonical
    one so previous audits are preserved.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        "name",
        ExecutionParameterDefinition(name="namespace", mandatory=False),
        ExecutionParameterDefinition(name="connection", mandatory=False),
        ExecutionParameterDefinition(name="profile_name", mandatory=False),
        ExecutionParameterDefinition(name="sample", mandatory=False, data_type="int"),
        ExecutionParameterDefinition(name="environment", mandatory=False),
        ExecutionParameterDefinition(name="force", mandatory=False, data_type="bool"),
        ExecutionParameterDefinition(
            name="new_version", mandatory=False, data_type="bool"
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        name: str,
        namespace: str | None = None,
        connection: str | None = None,
        profile_name: str | None = None,
        sample: int | None = None,
        environment: str | None = None,
        force: bool = False,
        new_version: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.name = name
        self.namespace = namespace
        self.connection = connection
        self.profile_name = profile_name
        self.sample = sample
        self.environment = environment or "prd"
        self.force = force
        self.new_version = new_version
        self.execution_context.load_entities(entity_types=[EntityTypeNames.STRUCTURE])

    def run(self, **kwargs: Any) -> bool:
        self.log_info(
            f"Resolving structure '{self.name}'"
            + (f" in namespace '{self.namespace}'" if self.namespace else "")
        )
        registry = self.execution_context.entity_registry
        namespaced = registry.get_structure(
            entity_key=self.name,
            namespace=self.namespace,
        )
        resolved_namespace = namespaced.namespace
        structure = namespaced.model

        config = self.execution_context.project.structure_namespace_config
        mapping = config.get_mapping(namespace=resolved_namespace)
        connection_name = self.connection or mapping.default_connection_name
        schema = structure.get_property("schema") or mapping.schema_name
        database = structure.get_property("database") or mapping.database_name
        table = structure.name

        canonical_name = (
            table if self.environment == "prd" else f"{table}_{self.environment}"
        )
        audit_name = self._resolve_audit_name(canonical_name)

        file_output_service = FileOutputService(
            root_folder_path=self.execution_context.get_nld_root_folder_path(),
            override_output_folder_path=(
                self.execution_context.project.entities_root_folder_path
            ),
            entity_layout=self.execution_context.project.entity_layout,
        )
        output_path = file_output_service.resolve_output_file_path(
            file_name=f"{audit_name}.yml",
            internal_folder_name=AUDIT_INTERNAL_FOLDER,
            namespace=resolved_namespace,
        )
        if not self.new_version and os.path.exists(output_path) and not self.force:
            self.log_warn(
                f"Audit already exists at {output_path}; pass --force to overwrite "
                "or --new-version to keep a timestamped copy. Skipping."
            )
            return True

        self.log_info(
            f"Opening connection '{connection_name}'"
            + (f" with profile '{self.profile_name}'" if self.profile_name else "")
        )
        connector = self.execution_context.get_data_connector(
            connection_name,
            profile_name=self.profile_name,
            open_connection=True,
        )
        if not connector.supports_data_profiling():
            raise ValueError(
                f"Connection '{connection_name}' "
                f"(type {connector.connection_wrapper.type}) does not support data "
                "profiling; structure audits require a profiling-capable engine."
            )

        business_fields = [
            field
            for field in structure.get_fields()
            if not self._is_tracking_field(field)
        ]
        pk_names = {field.name for field in structure.get_primary_key_fields()}
        date_field = self._date_coverage_field(structure)

        sample_info = (
            f"a sample of at most {self.sample} row(s)"
            if self.sample
            else "the full table"
        )
        self.log_info(
            f"Profiling {schema}.{table} over {len(business_fields)} column(s) "
            f"on {sample_info}; this queries the live database and may take a while"
        )
        profile = connector.get_data_profiler().profile(
            schema_name=schema,
            table_name=table,
            columns=[
                ColumnProfileSpec(name=field.name, data_type=field.data_type or None)
                for field in business_fields
            ],
            date_field=date_field,
            sample=self.sample,
        )

        if profile.row_count < MIN_REPRESENTATIVE_ROWS:
            self.log_warn(
                f"Table {schema}.{table} holds only {profile.row_count} row(s); "
                f"audits are meant to run on at least {MIN_REPRESENTATIVE_ROWS} rows "
                "to be representative."
            )

        audit = self._build_audit(
            audit_name=audit_name,
            resolved_namespace=resolved_namespace,
            structure_table=table,
            schema=schema,
            database=database,
            connection_name=connection_name,
            connector_type=cast(
                SQLDataConnector[Any], connector
            ).connection_wrapper.type,
            business_fields=business_fields,
            pk_names=pk_names,
            date_field=date_field,
            profile=profile,
        )

        file_output_service.write_yaml_file(
            nld_base_model=audit,
            internal_folder_name=AUDIT_INTERNAL_FOLDER,
            namespace=resolved_namespace,
        )
        self.log_info(
            f"Wrote audit '{audit_name}' ({len(audit.columns)} column(s), "
            f"{profile.row_count} row(s)) to {output_path}"
        )
        return True

    def _resolve_audit_name(self, canonical_name: str) -> str:
        """Stamps the audit name with the current time when --new-version is set."""
        if not self.new_version:
            return canonical_name
        return f"{canonical_name}.{get_current_datetime_as_version_str()}"

    # -- audit assembly (TableProfile -> StructureAudit) ---------------------

    def _build_audit(
        self,
        audit_name: str,
        resolved_namespace: str | None,
        structure_table: str,
        schema: str,
        database: str,
        connection_name: str,
        connector_type: str | None,
        business_fields: list[Field],
        pk_names: set[str],
        date_field: str | None,
        profile: TableProfile,
    ) -> StructureAudit:
        columns: dict[str, AuditColumn] = {}
        for field in business_fields:
            measured = profile.columns.get(field.name)
            coverage = AuditColumnCoverage()
            distribution = None
            if measured is not None:
                coverage = AuditColumnCoverage(
                    non_null=measured.non_null,
                    pct=measured.pct,
                    distinct=measured.distinct,
                    min=measured.min,
                    max=measured.max,
                )
                if measured.distribution is not None:
                    distribution = AuditDistribution(
                        top_n=measured.distribution.top_n,
                        truncated=measured.distribution.truncated,
                        values=[
                            AuditDistributionValue(
                                value=entry.value,
                                count=entry.count,
                                pct=entry.pct,
                            )
                            for entry in measured.distribution.values
                        ],
                    )
            columns[field.name] = AuditColumn(
                name=field.name,
                data_type=field.data_type or None,
                nullable=not field.is_mandatory(),
                primary_key=field.name in pk_names,
                coverage=coverage,
                distribution=distribution,
            )

        date_coverage = None
        if date_field and (profile.date_from or profile.date_to):
            date_coverage = AuditDateCoverage(
                field_characterisation=(
                    FieldCharacterisationDefinitionNames.REC_SOURCE_EXTRACTION_TST.value
                ),
                **{"from": profile.date_from},
                to=profile.date_to,
            )

        structure_ref = (
            structure_table
            if not resolved_namespace or resolved_namespace == "."
            else f"{resolved_namespace}.{structure_table}"
        )
        return StructureAudit(
            name=audit_name,
            description=f"Data analysis audit of {structure_table}",
            structure=NldEntityReference(structure_ref),
            target=AuditTarget(
                environment=self.environment,
                connection=connection_name,
                connector_type=connector_type,
                database=database,
                schema=schema,
                table=structure_table,
            ),
            metadata=AuditMetadata(
                audited_at=get_current_datetime().isoformat(),
                row_count=profile.row_count,
                sampling=AuditSampling(
                    sampled=profile.sampled,
                    method="random_limit" if profile.sampled else None,
                    sample_size=profile.sample_size if profile.sampled else None,
                    fraction=profile.fraction if profile.sampled else None,
                ),
                date_coverage=date_coverage,
            ),
            columns=columns,
        )

    # -- structure-side helpers ---------------------------------------------

    @staticmethod
    def _is_tracking_field(field: Field) -> bool:
        name = field.name
        if name in _TRACKING_EXACT_NAMES:
            return True
        if name.startswith(_TRACKING_NAME_PREFIXES):
            return True
        return any(
            char.startswith("rec_") for char in field.get_characterisation_names()
        )

    @staticmethod
    def _date_coverage_field(structure: Any) -> str | None:
        field = structure.get_single_field_with_characterisation(
            FieldCharacterisationDefinitionNames.REC_SOURCE_EXTRACTION_TST.value
        )
        return field.name if field is not None else None
