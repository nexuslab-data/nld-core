import os.path
from pathlib import Path
from typing import Any

from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    Template,
    TemplateSyntaxError,
    meta,
)

from nld.pydantic import NldBaseModel
from nld.utils.jinja_utils import (
    get_template_from_file_path,
    get_template_variables,
    interpret_parameters,
)


class JinjaRenderEntry:
    template_path: str
    template: Template
    output_file_name_pattern: str
    parameter_level: str | None = None

    def __init__(
        self,
        template_path: str,
        template: Template,
        output_file_name_pattern: str,
        parameter_level: str | None = None,
    ) -> None:
        self.template_path = template_path
        self.template = template
        self.output_file_name_pattern = output_file_name_pattern
        self.parameter_level = parameter_level

    def render_string(self, parameters: dict[str, Any]) -> str:
        try:
            return self.template.render(**parameters)
        except TemplateSyntaxError as e:
            raise ValueError(
                f"Invalid jinja2 syntax in file: '{self.template_path}' - {e}"
            ) from e

    def get_template_variables(self, env: Environment | None = None) -> set[str]:
        env = env if env is not None else Environment(undefined=StrictUndefined)
        try:
            parsed_template = env.parse(self.template_path)
        except TemplateSyntaxError as e:
            raise ValueError(f"Invalid Jinja2 syntax: {e}") from e
        return meta.find_undeclared_variables(parsed_template)

    def get_output_file_name_expected_params(self) -> set[str]:
        return get_template_variables(self.output_file_name_pattern)

    def build_filename(self, params: dict[str, Any]) -> str:
        missing_params = self.get_output_file_name_expected_params() - params.keys()
        if missing_params:
            raise ValueError(
                f"Missing parameters for file name pattern: {missing_params}."
            )
        try:
            return Template(str(self.output_file_name_pattern)).render(**params).strip()
        except Exception as e:
            raise ValueError(
                f"Failed to render file name with pattern "
                f"'{self.output_file_name_pattern}': {e}"
            ) from e


class JinjaRenderer:
    def __init__(
        self,
        rendering_root_folder_path: str,
        expected_parameters: list[str] | None = None,
    ) -> None:
        self.rendering_root_folder_path = Path(rendering_root_folder_path)
        self.expected_parameters = (
            expected_parameters if expected_parameters is not None else []
        )
        self.env = Environment(
            loader=FileSystemLoader(str(self.rendering_root_folder_path)),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.render_entries: list[JinjaRenderEntry] = []
        self.init_render_entries(rendering_root_folder_path)

    def init_render_entries(self, rendering_root_folder_path: str) -> None:
        all_files = [
            f for f in Path(rendering_root_folder_path).rglob("*") if f.is_file()
        ]
        for file in all_files:
            relative_path = file.relative_to(rendering_root_folder_path)
            output_file_name_pattern = (
                relative_path
                if relative_path.suffix != ".j2"
                else os.path.splitext(relative_path)[0]
            )

            self.render_entries.append(
                JinjaRenderEntry(
                    template_path=str(file),
                    template=get_template_from_file_path(str(file)),
                    output_file_name_pattern=str(output_file_name_pattern),
                )
            )

    def render_files(
        self, output_folder_path: str, params: dict[str, Any], **kwargs: Any
    ) -> None:
        context_params = {
            k: v.model_dump() if isinstance(v, NldBaseModel) else v is str
            for k, v in kwargs.items()
            if k in self.expected_parameters
        }
        rendering_parameters = {
            **context_params,
            **interpret_parameters(params, context_params),
        }
        for render_entry in self.render_entries:
            content = render_entry.render_string(rendering_parameters)

            output_file = os.path.join(
                output_folder_path,
                render_entry.build_filename(rendering_parameters),
            )
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, "w") as file:
                file.write(content)
