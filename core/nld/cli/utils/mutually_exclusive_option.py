"""``MutuallyExclusiveOption`` — a reusable Click option subclass that
enforces "at most one of" (and optionally "exactly one of") across a
named group of options.

Usage::

    @click.option(
        "--flow-uid", "flow_uid",
        cls=MutuallyExclusiveOption,
        mutually_exclusive=["latest"],
        required_group=True,
    )
    @click.option(
        "--latest",
        is_flag=True,
        cls=MutuallyExclusiveOption,
        mutually_exclusive=["flow_uid"],
        required_group=True,
    )

Every option in the group must declare the class and cite each other in
``mutually_exclusive``. Set ``required_group=True`` on every option in the
group to additionally require that exactly one of them be provided.

The check uses ``ctx.get_parameter_source`` so an unset flag with
``default=False`` does not count as "provided".
"""

from collections.abc import Iterable, Mapping
from typing import Any

import click
from click.core import ParameterSource


def _to_cli(name: str) -> str:
    """Convert a Python parameter name to its CLI flag (``--foo-bar``)."""
    return name.replace("_", "-")


class MutuallyExclusiveOption(click.Option):
    """Click option that is mutually exclusive with one or more siblings."""

    def __init__(
        self,
        *args: Any,
        mutually_exclusive: Iterable[str] | None = None,
        required_group: bool = False,
        **kwargs: Any,
    ) -> None:
        self.mutually_exclusive: set[str] = set(mutually_exclusive or [])
        self.required_group = required_group
        super().__init__(*args, **kwargs)
        if self.mutually_exclusive:
            siblings = ", ".join(
                f"--{_to_cli(name)}" for name in sorted(self.mutually_exclusive)
            )
            extra = f"Mutually exclusive with: {siblings}."
            self.help = f"{self.help} {extra}".strip() if self.help else extra

    @staticmethod
    def _is_user_provided(ctx: click.Context, name: str) -> bool:
        source = ctx.get_parameter_source(name)
        return source is not None and source != ParameterSource.DEFAULT

    def handle_parse_result(
        self,
        ctx: click.Context,
        opts: Mapping[str, Any],
        args: list[str],
    ) -> tuple[Any, list[str]]:
        # Let Click record this option's source first so the checks below
        # can rely on ctx.get_parameter_source for every group member.
        result = super().handle_parse_result(ctx, opts, args)

        # ``self.name`` is typed as Optional on click.Parameter, but every
        # concrete option resolves to a real name by the time we get here.
        assert self.name is not None

        # Each option in the group triggers handle_parse_result; the check
        # should fire only once, from the last option to be processed.
        # We detect "last" by waiting until every group member has a
        # recorded ParameterSource — independent of declaration order.
        group: set[str] = self.mutually_exclusive | {self.name}
        if any(ctx.get_parameter_source(n) is None for n in group):
            return result

        provided = {n for n in group if self._is_user_provided(ctx, n)}

        if len(provided) > 1:
            flags = ", ".join(f"--{_to_cli(n)}" for n in sorted(provided))
            raise click.UsageError(f"options are mutually exclusive: {flags}")

        if self.required_group and not provided:
            flags = ", ".join(f"--{_to_cli(n)}" for n in sorted(group))
            raise click.UsageError(f"specify one of: {flags}")

        return result
