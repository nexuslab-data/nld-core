import os
from typing import TYPE_CHECKING

from jinja2 import Template

from nld.logging import log_info_default
from nld.pydantic import NldNamedBaseModel
from nld.utils.datetime_util import (
    get_current_datetime_as_filesystem_friendly_str,
)

from .structure_sql_renderer import (
    StructureSqlRenderer,
)

if TYPE_CHECKING:
    from nld.structure.structure import Structure, StructureAdapter


class SQLTemplateWrapper(NldNamedBaseModel):
    template: str = ""
    structure_adapter: "StructureAdapter | None" = None

    def generate_sql(
        self,
        structure: "Structure",
        output_folder: str,
        file_name: str,
    ) -> None:
        """
        Generates an SQL file by rendering the template with the given structure.
        """
        folder_name = output_folder or get_current_datetime_as_filesystem_friendly_str()

        structure_to_render = (
            self.structure_adapter.adapt_structure(original_structure=structure)
            if self.structure_adapter
            else structure
        )

        try:
            sql_statement = StructureSqlRenderer.create_statement(
                template=Template(self.template),
                structure=structure_to_render,
            )
        except Exception as e:
            raise ValueError(f"Failed to render SQL statement: {e}") from e

        output_dir = os.path.join("output", folder_name)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, file_name)

        with open(output_path, "w", encoding="utf-8") as file:
            file.write(sql_statement)

        log_info_default(f"SQL generated in {output_path}")
