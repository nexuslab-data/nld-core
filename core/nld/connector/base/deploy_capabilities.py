from __future__ import annotations

from nld.pydantic.base_model import NldBaseModel

# Engine-neutral ANSI synonyms only: any spelling specific to one
# engine (or engine family) is declared by that connector's
# capabilities, never here.
ANSI_COMPARABLE_DATA_TYPE_ALIASES: dict[str, str] = {
    "CHARACTER VARYING": "VARCHAR",
    "DECIMAL": "NUMERIC",
    "INT": "INTEGER",
    "TIMESTAMP WITHOUT TIME ZONE": "TIMESTAMP",
}


class ConnectorDeployCapabilities(NldBaseModel):
    """What one engine supports for structure deployment.

    The strategy resolver consults this instead of assuming: an
    unsupported in-place operation falls back to REBUILD or fails
    with a clear message, never a silent skip.
    ``comparable_data_type_aliases`` carries the engine's own type
    spellings mapped to their canonical comparable form.
    ``enforce_field_order_default`` is the effective value of a
    structure's ``enforce_field_order`` when it does not declare one
    explicitly (``None``): engines where a mismatched physical order
    is cheap/undesirable to leave alone default to ``False``, engines
    where declared order should be kept authoritative by default
    default to ``True``.
    ``add_column_positioned`` declares that the engine can ADD a
    column at a declared position (e.g. MySQL ``AFTER``): with field
    order enforced, engines without it must REBUILD when a new field
    is declared before an existing one; engines with it keep the
    plain ALTER path and their DDL builder carries the position.
    ``alter_column_type`` declares that the engine can change a
    column's type in place: engines without it (SQLite, whose ALTER
    TABLE only adds, renames and drops columns) REBUILD instead.
    ``alter_add_primary_key`` declares that the engine can add a
    primary key to an existing table: engines without it (SQLite,
    which has no ALTER TABLE ADD CONSTRAINT at all) get the key
    declared inline in the rebuilt table's CREATE instead.
    """

    dialect: str
    alter_add_primary_key: bool = True
    alter_column_set_default: bool
    alter_column_type: bool = True
    add_column_positioned: bool = False
    # Whether the reader can detect the views depending on a table.
    # When False the deploy cannot protect dependent views and warns
    # instead of silently no-opping.
    detects_dependent_views: bool = True
    comparable_characterisations: list[str]
    comparable_data_type_aliases: dict[str, str] = {}
    enforce_field_order_default: bool
    rename_column_in_place: bool
    rename_table_in_place: bool


def normalize_comparable_data_type(
    data_type: str,
    capabilities: ConnectorDeployCapabilities | None = None,
) -> str:
    """Normalize a data type to its canonical comparable form.

    Engines and readers spell the same physical type differently
    (``INTEGER`` vs ``INT``, ``CHARACTER VARYING`` vs ``VARCHAR``);
    comparing the canonical forms keeps the diff and the drift gate
    stable — a semantically-equal type never churns DDL or reads as
    drift. The ANSI synonyms apply first, then the engine-specific
    aliases carried by the connector capabilities (e.g. Snowflake
    ``INTEGER`` is ``NUMBER(38,0)``, so it compares equal to
    ``NUMERIC``).
    """
    upper_type = data_type.upper().strip() if data_type else ""
    base = ANSI_COMPARABLE_DATA_TYPE_ALIASES.get(upper_type, upper_type)
    if capabilities is None:
        return base
    return capabilities.comparable_data_type_aliases.get(base, base)
