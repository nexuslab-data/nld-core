from collections.abc import Iterable, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, create_model
from pydantic import Field as PydanticField

from nld.pydantic import NldBaseModel
from nld.structure.field.field import Field
from nld.structure.structure.structure import Structure

ExportMode = Literal["read", "create", "patch"]

MODE_READ: ExportMode = "read"
MODE_CREATE: ExportMode = "create"
MODE_PATCH: ExportMode = "patch"

EXPORT_MODES: tuple[ExportMode, ...] = (MODE_READ, MODE_CREATE, MODE_PATCH)

MODE_MODEL_NAME_SUFFIXES: dict[str, str] = {
    MODE_READ: "",
    MODE_CREATE: "Create",
    MODE_PATCH: "Patch",
}

# Portable data types the export understands, keyed by their normalised
# spelling. The set is deliberately the subset a single structure definition
# can be deployed with on every supported engine; anything else is rejected
# rather than silently exported as a string.
DATA_TYPE_TO_PYTHON_TYPE: dict[str, Any] = {
    "character_varying": str,
    "varchar": str,
    "character": str,
    "char": str,
    "text": str,
    "string": str,
    "integer": int,
    "int": int,
    "smallint": int,
    "bigint": int,
    "numeric": Decimal,
    "decimal": Decimal,
    "double_precision": float,
    "double": float,
    "float": float,
    "real": float,
    "boolean": bool,
    "bool": bool,
    "date": date,
    "time": time,
    "timestamp": datetime,
    "timestamp_with_time_zone": datetime,
    "timestamptz": datetime,
    "uuid": UUID,
    "json": Any,
    "jsonb": Any,
    "variant": Any,
}


class StructureExportError(ValueError):
    """Raised when a structure cannot be exported to a Pydantic model."""


def normalise_token(token: str) -> str:
    """Normalise a data type or characterisation to its comparison form."""
    return "_".join(token.strip().lower().replace("-", " ").replace("_", " ").split())


def to_pascal_case(name: str) -> str:
    """Turn a structure or field name into a Pydantic-friendly class name."""
    parts = [part for part in normalise_token(name).split("_") if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Model"


def _resolve_python_type(field: Field) -> Any:
    """Resolve the Python annotation for a leaf field."""
    normalised = normalise_token(field.data_type)
    if normalised not in DATA_TYPE_TO_PYTHON_TYPE:
        raise StructureExportError(
            f"Field '{field.name}' has data type '{field.data_type}' which has "
            f"no portable Python equivalent. Supported data types are: "
            f"{sorted(DATA_TYPE_TO_PYTHON_TYPE)}"
        )
    return DATA_TYPE_TO_PYTHON_TYPE[normalised]


def _coerce_default(field: Field, python_type: Any) -> Any:
    """Coerce the declared default to the field's Python type.

    Structure defaults are database expressions as much as literals, so a
    value that does not convert (``CURRENT_TIMESTAMP`` on a timestamp column)
    yields ``None`` rather than an invalid model default.
    """
    value = field.default_value
    if value is None:
        return None
    if python_type is Any or isinstance(value, python_type):
        return value
    try:
        if python_type is bool:
            return str(value).strip().lower() in ("true", "1", "yes")
        if python_type in (int, float, Decimal, str, UUID):
            return python_type(value)
        if python_type is date:
            return date.fromisoformat(str(value))
        if python_type is datetime:
            return datetime.fromisoformat(str(value))
        if python_type is time:
            return time.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return None


def _field_characterisation_tokens(
    structure: Structure,
    field: Field,
) -> set[str]:
    """Collect every characterisation naming a field, field- and structure-level.

    Structure characterisations are included so that a caller excluding
    ``primary key`` drops the key fields, the same way excluding
    ``rec_insert_tst`` drops the insert timestamp column.
    """
    tokens = {
        normalise_token(characterisation)
        for characterisation in field.get_characterisation_names()
    }
    for structure_characterisation in structure.get_characterisations():
        linked_fields = structure_characterisation.linked_fields or []
        if field.name in linked_fields:
            tokens.add(normalise_token(structure_characterisation.characterisation))
    return tokens


def _build_field_definition(
    structure: Structure,
    field: Field,
    mode: ExportMode,
    exclude_characterisations: Sequence[str],
    model_name: str,
) -> tuple[Any, Any]:
    """Build the ``(annotation, FieldInfo)`` pair for one exported field."""
    if field.fields:
        python_type: Any = _build_model(
            structure=structure,
            fields=list(field.fields.values()),
            mode=mode,
            exclude_characterisations=exclude_characterisations,
            model_name=f"{model_name}{to_pascal_case(field.name)}",
        )
    else:
        python_type = _resolve_python_type(field=field)

    constraints: dict[str, Any] = {}
    if field.description:
        constraints["description"] = field.description
    if python_type is str and field.length > 0:
        constraints["max_length"] = field.length
    if python_type is Decimal and field.length > 0:
        constraints["max_digits"] = field.length
        constraints["decimal_places"] = field.precision

    # A mandatory field that declares a default is not required *from the
    # caller*: the default is exactly the value to use when nothing is sent,
    # whether it is a literal or an expression the engine evaluates. Only the
    # read model keeps it required, because a stored row always has a value.
    is_required = (
        mode == MODE_READ
        and field.is_mandatory()
        or mode == MODE_CREATE
        and field.is_mandatory()
        and field.default_value is None
    )
    if is_required:
        return python_type, PydanticField(**constraints)

    return (
        python_type | None if python_type is not Any else Any,
        PydanticField(
            default=None
            if mode == MODE_PATCH
            else _coerce_default(
                field=field,
                python_type=python_type,
            ),
            **constraints,
        ),
    )


def _build_model(
    structure: Structure,
    fields: Iterable[Field],
    mode: ExportMode,
    exclude_characterisations: Sequence[str],
    model_name: str,
) -> type[NldBaseModel]:
    """Build one Pydantic model from an iterable of structure fields."""
    excluded_tokens = {
        normalise_token(characterisation)
        for characterisation in exclude_characterisations
    }

    field_definitions: dict[str, Any] = {}
    for field in fields:
        tokens = _field_characterisation_tokens(structure=structure, field=field)
        if tokens & excluded_tokens:
            continue
        field_definitions[field.name] = _build_field_definition(
            structure=structure,
            field=field,
            mode=mode,
            exclude_characterisations=exclude_characterisations,
            model_name=model_name,
        )

    base_model: type[NldBaseModel] = NldBaseModel
    if mode == MODE_PATCH:
        base_model = type(
            f"{model_name}Base",
            (NldBaseModel,),
            {"model_config": ConfigDict(extra="forbid")},
        )

    return create_model(
        model_name,
        __base__=base_model,
        **field_definitions,
    )


def build_pydantic_model(
    structure: Structure,
    *,
    mode: ExportMode = MODE_READ,
    exclude_characterisations: Sequence[str] = (),
    model_name: str | None = None,
) -> type[NldBaseModel]:
    """Export a structure as a Pydantic model.

    The three modes cover the three shapes an application needs from the same
    table definition: ``read`` mirrors the stored row, ``create`` is the same
    minus whatever the caller excludes (the primary key and the lifecycle
    columns the server fills in), and ``patch`` makes every field optional and
    forbids unknown keys so a partial update cannot silently drop a typo.

    Args:
        structure: The structure to export, templates included.
        mode: One of ``read``, ``create`` or ``patch``.
        exclude_characterisations: Characterisations whose fields are dropped.
            Matched against both the field's own characterisations and the
            structure characterisations linking it, so ``primary key`` works
            alongside ``rec_insert_tst``.
        model_name: Name of the generated class. Defaults to the structure name
            in PascalCase, suffixed with the mode for ``create`` and ``patch``.

    Returns:
        A new ``NldBaseModel`` subclass.

    Raises:
        StructureExportError: If the mode is unknown or a field carries a data
            type with no portable Python equivalent.

    Example:
        >>> model = build_pydantic_model(
        ...     structure,
        ...     mode="create",
        ...     exclude_characterisations=["primary key", "rec_insert_tst"],
        ... )
    """
    if mode not in EXPORT_MODES:
        raise StructureExportError(
            f"Unknown export mode '{mode}'. Known modes are: {list(EXPORT_MODES)}"
        )

    resolved_model_name = model_name or (
        f"{to_pascal_case(structure.name)}{MODE_MODEL_NAME_SUFFIXES[mode]}"
    )
    return _build_model(
        structure=structure,
        fields=structure.get_all_fields(),
        mode=mode,
        exclude_characterisations=exclude_characterisations,
        model_name=resolved_model_name,
    )


def build_json_schema(
    structure: Structure,
    *,
    mode: ExportMode = MODE_READ,
    exclude_characterisations: Sequence[str] = (),
    model_name: str | None = None,
) -> dict[str, Any]:
    """Export a structure as a JSON Schema, through the Pydantic model."""
    model = build_pydantic_model(
        structure,
        mode=mode,
        exclude_characterisations=exclude_characterisations,
        model_name=model_name,
    )
    return model.model_json_schema()
