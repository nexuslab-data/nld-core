"""Resolve record-lifecycle timestamp handling from field characterisations.

Both the SQL write strategies (``INSERT ... SELECT ... ON CONFLICT``) and the
seed write strategies (bulk ``VALUES`` insert) must populate the standard
tracking timestamps ``ts_inserted_at`` (``rec_insert_tst``) and
``ts_updated_at`` (``rec_last_update_tst``) and honour the
``exclude_from_upsert_*`` characterisations. This module is the single source of
truth for that policy so both paths behave identically.
"""

from nld.structure import Structure
from nld.structure.field.field_characterisation_definition import (
    FieldCharacterisationDefinitionNames,
)

CURRENT_TIMESTAMP_EXPRESSION = "CURRENT_TIMESTAMP"


def resolve_upsert_field_params(
    target_structure: Structure | None,
) -> tuple[list[str] | None, dict[str, str] | None, list[str] | None]:
    """Resolve UPSERT field parameters from field characterisations.

    Returns ``(exclude_from_update, expression_overrides, exclude_from_match)``.

    The insert timestamp field (``REC_INSERT_TST``) is excluded from the
    ``UPDATE SET`` clause (insert-only), and so is the insert user field
    (``REC_INSERT_BY``). The last update timestamp field
    (``REC_LAST_UPDATE_TST``) is overridden with ``CURRENT_TIMESTAMP`` on
    update; ``REC_LAST_UPDATE_BY`` carries no SQL override because a flow
    execution has no acting user. Fields characterised
    ``EXCLUDE_FROM_UPSERT_UPDATE`` are excluded from
    both ``UPDATE SET`` and change detection; ``EXCLUDE_FROM_UPSERT_MATCH``
    fields are updated but excluded from change detection.
    """
    if target_structure is None:
        return None, None, None

    exclude_from_update: list[str] = []
    expression_overrides: dict[str, str] = {}
    exclude_from_match: list[str] = []

    insert_tst_field = target_structure.get_field_name_with_characterisation(
        FieldCharacterisationDefinitionNames.REC_INSERT_TST,
    )
    if insert_tst_field is not None:
        exclude_from_update.append(insert_tst_field)

    insert_by_field = target_structure.get_field_name_with_characterisation(
        FieldCharacterisationDefinitionNames.REC_INSERT_BY,
    )
    if insert_by_field is not None and insert_by_field not in exclude_from_update:
        exclude_from_update.append(insert_by_field)

    update_tst_field = target_structure.get_field_name_with_characterisation(
        FieldCharacterisationDefinitionNames.REC_LAST_UPDATE_TST,
    )
    if update_tst_field is not None:
        expression_overrides[update_tst_field] = CURRENT_TIMESTAMP_EXPRESSION

    for field_name in target_structure.get_field_names_with_characterisation(
        FieldCharacterisationDefinitionNames.EXCLUDE_FROM_UPSERT_UPDATE,
    ):
        if field_name not in exclude_from_update:
            exclude_from_update.append(field_name)

    for field_name in target_structure.get_field_names_with_characterisation(
        FieldCharacterisationDefinitionNames.EXCLUDE_FROM_UPSERT_MATCH,
    ):
        exclude_from_match.append(field_name)

    return (
        exclude_from_update or None,
        expression_overrides or None,
        exclude_from_match or None,
    )


def resolve_technical_tracking_timestamp_expressions(
    target_structure: Structure | None,
    existing_columns: list[str],
) -> dict[str, str]:
    """Resolve the technical tracking timestamp columns to inject on insert.

    Returns a mapping of column name to the SQL expression that populates it
    (always ``CURRENT_TIMESTAMP``), for the ``rec_insert_tst`` and
    ``rec_last_update_tst`` fields that are *not already* provided in
    ``existing_columns`` (e.g. supplied by a seed CSV).

    These fields are contributed by the standard tracking template and carry no
    database default, so a seed load that does not write them explicitly would
    leave them ``NULL``. Injecting ``CURRENT_TIMESTAMP`` mirrors the SQL flow
    path, where the same timestamps are set through the field-lineage
    expression.
    """
    if target_structure is None:
        return {}

    technical_tracking_timestamp_columns: dict[str, str] = {}
    existing = set(existing_columns)
    for characterisation in (
        FieldCharacterisationDefinitionNames.REC_INSERT_TST,
        FieldCharacterisationDefinitionNames.REC_LAST_UPDATE_TST,
    ):
        field_name = target_structure.get_field_name_with_characterisation(
            characterisation,
        )
        if field_name is not None and field_name not in existing:
            technical_tracking_timestamp_columns[field_name] = (
                CURRENT_TIMESTAMP_EXPRESSION
            )
    return technical_tracking_timestamp_columns
