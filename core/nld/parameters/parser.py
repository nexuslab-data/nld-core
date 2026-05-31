import argparse
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from .execution_params_def import (
    ExecutionParameterDefinition,
)


def _python_type_for(
    data_type: str | None,
) -> type[str] | type[int] | type[float] | Callable[[str], bool]:
    if data_type in (None, "str"):
        return str
    if data_type == "int":
        return int
    if data_type == "float":
        return float
    if data_type == "bool":
        return _parse_bool  # custom
    if data_type == "list":
        return str  # parse later
    # fallback
    return str


def _parse_bool(v: str) -> bool:
    t = v.strip().lower()
    if t in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if t in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean: {v}")


class _ListAction(argparse.Action):
    """Accepts multiple input formats for list arguments.

    Accepts either:
      --keys a b c
    or
      --keys=a,b,c
    or mixed/repeated usage:
      --keys a,b --keys c
    """

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        current: list[str] = getattr(namespace, self.dest) or []
        if values is None:
            pass
        elif isinstance(values, str):
            parts = [p for p in (s.strip() for s in values.split(",")) if p]
            current.extend(parts)
        else:
            # list of strings (when nargs='+')
            for v in values:
                if isinstance(v, str):
                    current.extend([p for p in (s.strip() for s in v.split(",")) if p])
        setattr(namespace, self.dest, current or None)


def build_argparser_from_params(
    params: Iterable[ExecutionParameterDefinition],
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    for p in params:
        short_name = p.short_name or p.name
        flag = f"--{short_name.replace('_', '-')}"
        kwargs: dict[str, Any] = {"help": p.help_text}
        # bool flags: support --flag/--no-flag (explicit true/false also allowed)
        if p.data_type == "bool":
            # Allow: --limit-enabled true/false OR the pair of toggles
            group = parser.add_mutually_exclusive_group(required=False)
            group.add_argument(
                flag, dest=p.name, nargs="?", const=True, type=_parse_bool
            )
            group.add_argument(
                f"--no-{short_name.replace('_', '-')}",
                dest=p.name,
                action="store_false",
            )
            kwargs = {}  # handled by group
            if p.default_value is not None:
                parser.set_defaults(**{p.name: bool(p.default_value)})
        elif p.data_type == "list":
            # Accept both repeated and comma-separated
            parser.add_argument(flag, dest=p.name, nargs="+", action=_ListAction)
        else:
            kwargs["type"] = _python_type_for(p.data_type)
            if p.default_value is not None:
                kwargs["default"] = p.default_value
            parser.add_argument(flag, dest=p.name, **kwargs)
        # If param is mandatory and not a bool/list handled above, make it required
        if p.mandatory and p.data_type not in {"bool", "list"}:
            # reconfigure last added action as required
            parser._actions[-1].required = True  # safe here because we just added it
    return parser


def _validate_allowed_values(
    parameters: dict[str, Any], params: Iterable[ExecutionParameterDefinition]
) -> None:
    by_name = {p.name: p for p in params}
    for name, value in list(parameters.items()):
        param = by_name.get(name)
        if not param or param.allowed_values is None or value is None:
            continue
        allowed = set(param.allowed_values)
        if param.data_type == "list":
            bad = [v for v in value if v not in allowed]
            if bad:
                raise ValueError(
                    f"Invalid value(s) for '{name}': {bad}. Allowed: {sorted(allowed)}"
                )
        else:
            if value not in allowed:
                raise ValueError(
                    f"Invalid value for '{name}': {value}. Allowed: {sorted(allowed)}"
                )


def _apply_defaults_and_mandatory(
    parameters: dict[str, Any], params: Iterable[ExecutionParameterDefinition]
) -> None:
    for p in params:
        if parameters.get(p.name) is None and p.default_value is not None:
            parameters[p.name] = p.default_value
        if p.mandatory and parameters.get(p.name) is None:
            raise ValueError(f"Missing mandatory parameter: '{p.name}'")


def parse_parameters_from_cli(
    params: Iterable[ExecutionParameterDefinition],
) -> dict[str, Any]:
    parser = build_argparser_from_params(params)
    ns = parser.parse_args()  # uses sys.argv
    # Build param dict only with names we know about
    parsed: dict[str, Any] = {p.name: getattr(ns, p.name, None) for p in params}
    # Normalize empty lists -> None
    for k, v in list(parsed.items()):
        if isinstance(v, list) and len(v) == 0:
            parsed[k] = None
    _apply_defaults_and_mandatory(parsed, params)
    _validate_allowed_values(parsed, params)
    return parsed
