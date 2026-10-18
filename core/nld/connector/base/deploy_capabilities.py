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
    ``default_data_type_sizes`` maps a type to the ``(length,
    precision)`` the engine applies to a bare declaration of it.
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
    default_data_type_sizes: dict[str, tuple[int, int]] = {}
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


def normalize_comparable_type_size(
    data_type: str,
    length: int,
    precision: int,
    capabilities: ConnectorDeployCapabilities | None = None,
) -> tuple[int, int]:
    """Normalize a field size to its canonical comparable form.

    A bare declaration takes the engine default — Snowflake ``VARCHAR``
    is ``VARCHAR(16777216)`` and ``INTEGER`` is ``NUMBER(38,0)`` — and
    the size the engine applies is reported as ``(0, 0)`` when it is
    the default of the comparable type. A bare and an explicit default
    spelling therefore compare equal, and a bare declaration keeps the
    ``(0, 0)`` size its recorded schema snapshots were hashed with.

    The declared type is looked up before its comparable alias, since
    an alias can merge types with distinct defaults: a bare Snowflake
    ``CHAR`` is ``VARCHAR(1)``, so it normalizes to ``(1, 0)``.

    Example: ``("INTEGER", 0, 0)`` and ``("NUMBER", 38, 0)`` both
    normalize to ``(0, 0)`` on Snowflake, ``("NUMBER", 18, 2)`` stays.
    """
    if capabilities is None:
        return length, precision
    default_sizes = capabilities.default_data_type_sizes
    comparable_type = normalize_comparable_data_type(
        data_type,
        capabilities=capabilities,
    )
    size = (length, precision)
    if size == (0, 0):
        upper_type = data_type.upper().strip() if data_type else ""
        declared_type = ANSI_COMPARABLE_DATA_TYPE_ALIASES.get(upper_type, upper_type)
        size = default_sizes.get(
            declared_type,
            default_sizes.get(comparable_type, size),
        )
    return (0, 0) if size == default_sizes.get(comparable_type) else size
