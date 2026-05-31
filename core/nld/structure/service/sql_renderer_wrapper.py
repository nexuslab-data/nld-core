import os
import re
from typing import TYPE_CHECKING, ClassVar

from jinja2 import Template

from nld.exceptions import MissingObjectException
from nld.pydantic import NldNamedBaseModel
from nld.utils.jinja_utils import get_template_variables

from .sql_template_wrapper import SQLTemplateWrapper

if TYPE_CHECKING:
    from nld.structure.structure import Structure, StructureAdapter


class SQLRenderEntry(NldNamedBaseModel):
    file_name_pattern: str = ""
    adapter: "StructureAdapter | None" = None

    DEFAULT_PATTERN: ClassVar[str] = "{{ structure_name }}.sql"

    def _suffix_from_name(self) -> str:
        """Extracts the suffix from a template filename."""
        base = os.path.basename(self.name)
        match = re.match(r".*\.([^.]+)\.sql$", base, flags=re.IGNORECASE)
        return match.group(1).lower() if match else os.path.splitext(base)[0].lower()

    def build_filename(self, structure_name: str, params: dict[str, str]) -> str:
        """Constructs the final filename according to the file name pattern."""
        pattern = self.file_name_pattern or self.DEFAULT_PATTERN
        context = {
            **params,
            "structure_name": structure_name,
            "suffix": self._suffix_from_name(),
        }
        expected_params = get_template_variables(pattern)
        missing_params = expected_params - context.keys()
        if missing_params:
            raise ValueError(
                f"Missing parameters for file name pattern: {missing_params}."
            )

        try:
            return Template(pattern).render(**context).strip()
        except Exception as e:
            raise ValueError(
                f"Failed to render file name with pattern "
                f"'{self.file_name_pattern}': {e}"
            ) from e


class SQLRendererWrapper(NldNamedBaseModel):
    renderer: list[SQLRenderEntry] = []

    def render_all(
        self,
        structure: "Structure",
        params: dict[str, str],
        output_folder: str,
        templates_dict: dict[str, SQLTemplateWrapper],
        adapters_dict: "dict[str, StructureAdapter]",
    ) -> None:
        """Renders all SQL templates for the given structure."""
        for entry in self.renderer:
            template_wrapper = templates_dict.get(entry.name)
            if template_wrapper is None:
                raise MissingObjectException(SQLTemplateWrapper, entry.name)

            adapter_obj = None
            if entry.adapter:
                key = entry.adapter.name
                adapter_obj = adapters_dict.get(key)
                if adapter_obj is None:
                    from nld.structure.structure import StructureAdapter

                    raise MissingObjectException(StructureAdapter, key)

            wrapper = SQLTemplateWrapper(
                name=entry.name,
                template=template_wrapper.template,
                structure_adapter=adapter_obj,
            )

            file_name = entry.build_filename(structure.name, params)

            try:
                wrapper.generate_sql(structure, output_folder, file_name)
            except Exception as e:
                raise ValueError(
                    f"Failed to render SQL statement for {entry.name}: {e}"
                ) from e
