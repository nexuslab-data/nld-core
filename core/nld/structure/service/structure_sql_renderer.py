from typing import TYPE_CHECKING, Any

from jinja2 import Template

from nld.utils.datetime_util import get_current_datetime

if TYPE_CHECKING:
    from nld.structure.structure import (
        Structure,
        StructureNamespace,
    )


class StructureSqlRenderer:
    """
    Structure SQL Renderer.

    Provides method to convert a structure to a dictionary interpretable by
    jinja. This class can be inherited to provide different dictionary
    interpretations.
    """

    @classmethod
    def get_structure_dict_for_jinja_rendering(
        cls, structure: "Structure"
    ) -> dict[str, Any]:
        """
        Get a structure dictionary for jinja rendering.

        Output Dictionary contains:
            - All structure and field attributes (with additional field-level
              information provided for mandatory fields)
            - last_update_tst_field: last update timestamp field, if available
            - source_last_update_tst_field: source last update timestamp field
            - insert_tst_field: insert timestamp field, if available

        Parameters
        -----------
            structure: Structure - A structure

        Returns
        -----------
            The structure dictionary for jinja rendering
        """
        structure_dict = structure.as_dict()  # type: ignore[attr-defined]

        # Primary Key specific rule
        from nld.structure.structure import (
            StructureCharacterisationDefinitionNames,
        )

        pk_characterisation = structure.get_characterisation(
            StructureCharacterisationDefinitionNames.PRIMARY_KEY
        )
        if pk_characterisation is not None:
            structure_dict["primary_key"] = pk_characterisation.to_dict()

        structure_dict["last_update_tst_field"] = structure.get_last_update_tst_field()
        structure_dict["source_last_update_tst_field"] = (
            structure.get_source_last_update_tst_field()
        )
        structure_dict["insert_tst_field"] = structure.get_insert_tst_field()
        return structure_dict  # type: ignore[no-any-return]

    @classmethod
    def get_generic_param_dict(cls) -> dict[str, str]:
        """
        Get the generic parameter dictionary.

        Output Dictionary contains :
            - cur_date_str : the current date formatted as %d-%m-Y

        Returns
        -------
            A dictionary with all generic parameters (not input specific)
        """
        return {"cur_date_str": get_current_datetime().strftime("%d-%m-%Y")}

    @classmethod
    def get_template_input_dict(
        cls,
        structure: "Structure",
        namespace: "StructureNamespace | None" = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Get the input dictionary for template rendering.

        The created dictionary contains:
            - structure: Dictionary of structure attributes, created using
              the get_structure_jinja_dict method
            - gen_params: Dictionary of general parameters, including class
              generic parameters and the parameters provided as input

        Parameters
        ----------
        structure : Structure
            The structure
        namespace : StructureNamespace
            The namespace for this structure
        params : Dict[str, str]
            The specific parameters for the generation

        Returns
        -------
            The Dictionary for template rendering
        """
        if params is None:
            params = {}
        gen_param_dict = cls.get_generic_param_dict()
        gen_param_dict.update(params)
        return {
            "namespace": (namespace.as_dict() if namespace is not None else {}),  # type: ignore[attr-defined]
            "structure": cls.get_structure_dict_for_jinja_rendering(structure),
            "gen_params": gen_param_dict,
        }

    @classmethod
    def create_statement(
        cls,
        template: Template,
        structure: "Structure",
        namespace: "StructureNamespace | None" = None,
        params: dict[str, str] | None = None,
    ) -> str:
        """
        Create a statement using the provided template for the input
        namespace, structure and parameters.

        Parameters
        ----------
        template : Template
            The template used for statement rendering
        structure : Structure
            The structure
        namespace : StructureNamespace
            The namespace for this structure
        params : Dict, optional
            A dictionary of parameters, which can be used by the template

        Returns
        -------
            The rendered statement
        """
        if params is None:
            params = {}
        return template.render(
            cls.get_template_input_dict(
                structure=structure, namespace=namespace, params=params
            )
        )
