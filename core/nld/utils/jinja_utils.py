from typing import Any

from jinja2 import (
    Environment,
    StrictUndefined,
    Template,
    TemplateSyntaxError,
    meta,
)

JINJA2_FILE_STANDARD_REGEX = r".*\.jinja2$"


def get_template_from_file_path(file_path: str) -> Template:
    with open(file_path) as f:
        template_content = f.read()
    return Template(template_content)


def render_template(template_str: str | None, *args: Any, **kwargs: Any) -> str:
    if template_str is None:
        return ""
    return Template(template_str).render(*args, **kwargs).strip()


def render_template_with_none_return_allowed(
    template_str: str | None, *args: Any, **kwargs: Any
) -> str | None:
    if template_str is None:
        return None
    render_result = Template(template_str).render(*args, **kwargs).strip()
    return render_result if render_result else None


def get_template_variables(template_str: str) -> set[str]:
    """
    Extracts the set of variables that are expected (not defined in the template).
    """
    env = Environment(undefined=StrictUndefined)
    try:
        parsed_template = env.parse(template_str)
    except TemplateSyntaxError as e:
        raise ValueError(f"Invalid Jinja2 syntax: {e}") from e
    return meta.find_undeclared_variables(parsed_template)


def interpret_parameters(
    params: dict[str, str], extra_params: dict[str, Any]
) -> dict[str, str]:
    return {
        key: (
            render_template(value, extra_params)
            if value is not None and isinstance(value, str)
            else value
        )
        for key, value in params.items()
    }
