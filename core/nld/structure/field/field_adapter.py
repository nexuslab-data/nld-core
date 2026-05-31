from typing import Any

from pydantic import Field as PydanticField

from nld.pydantic import NldBaseModel, NldNamedBaseModel, NldNamespacedBaseModelWrapper
from nld.utils.jinja_utils import (
    render_template,
    render_template_with_none_return_allowed,
)

from .field import Field
from .field_characterisation import (
    FieldCharacterisation,
)
from .field_characterisation_def import (
    FieldCharacterisationDefinitionNames,
    FieldCharacterisationDefinitions,
)
from .field_format_adapter import (
    FieldFormatAdapter,
)


class FieldNamingMapping(NldBaseModel):
    """
    Example of field naming mapping dictionary:
        {
            'prefix' : 'PREFIX_VALUE'
            , 'suffix' : 'SUFFIX_VALUE'
            , 'rules' :
                {
                'name' : {'override_name' : 'PDT_CAT_LV0'}
                , 'sdesc1' : {'override_name' : 'PDT_CAT_LV0_SHT_FRE_DSC'}
                , 'sdesc2' : {'override_name' : 'PDT_CAT_LV0_SHT_ENG_DSC'}
                , 'ldesc1' : {'override_name' : 'PDT_CAT_LV0_LNG_FRE_DSC'}
                , 'ldesc2' : {'override_name' : 'PDT_CAT_LV0_LNG_ENG_DSC'}
                }
        }
    """

    prefix: str = PydanticField(
        default="",
        description="Prefix to apply to field names",
    )
    suffix: str = PydanticField(
        default="",
        description="Suffix to apply to field names",
    )
    rules: dict[str, dict[str, str]] = PydanticField(
        default_factory=dict,
        description="Field-specific naming rules",
    )

    def get_fields_mapped(self) -> list[str]:
        return list(self.rules.keys())

    def has_specific_naming_rule(self, name: str) -> bool:
        """
        Checks if the provided field name has a specific naming rule

        Parameters
        -----------
            name : the field name to check

        Returns
        -----------
            True if the field name has a specific naming rule, False otherwise
        """
        field_naming_rule = self.get_field_naming_rule(name)
        if field_naming_rule is None:
            return False
        return "rule" in field_naming_rule.keys()

    def get_field_naming_rule(self, name: str) -> dict[str, str] | None:
        """
        Get the field naming rule for a specific field name

        Parameters
        -----------
            name : the field name

        Returns
        -----------
            The field naming rule for the provided field name
        """
        if name in list(self.rules.keys()):
            return self.rules[name]
        return None

    def get_target_field_name(self, name: str) -> str:
        """
        Get the target field name for an input field name

        Parameters
        -----------
            name : the field name

        Returns
        -----------
            The target field name for this field naming rules
        """
        fld_specific_naming_rule = self.get_field_naming_rule(name)
        if fld_specific_naming_rule is None:
            return name
        if "override_name" in fld_specific_naming_rule.keys():
            return fld_specific_naming_rule["override_name"]
        rule = fld_specific_naming_rule["rule"]
        rule_params = {
            "field_general_prefix": self.prefix,
            "field_general_suffix": self.suffix,
            "prefix": (
                fld_specific_naming_rule["prefix"]
                if "prefix" in fld_specific_naming_rule.keys()
                else ""
            ),
            "suffix": (
                fld_specific_naming_rule["suffix"]
                if "suffix" in fld_specific_naming_rule.keys()
                else ""
            ),
        }
        return render_template(rule, **rule_params)


class FieldAdapter(NldNamedBaseModel):
    name_rule: str = PydanticField(
        default="{{original_field.name}}",
        description="Jinja template for field name transformation",
    )
    description_rule: str = PydanticField(
        default="{{original_field.description}}",
        description="Jinja template for field description transformation",
    )
    short_description_rule: str | None = PydanticField(
        default=None,
        description="Jinja template for field short description transformation",
    )
    all_fields_optional: bool = PydanticField(
        default=False,
        description="Whether all fields should be made optional",
    )
    orig_to_new_characterisation_mapping: dict[str, str] | None = PydanticField(
        default=None,
        description="Mapping from original to new characterisation names",
    )
    field_format_adapter: FieldFormatAdapter | None = PydanticField(
        default=None,
        description="Field format adapter for data type transformations",
    )
    field_names_to_exclude: list[str] | None = PydanticField(
        default=None,
        description="List of field names to exclude from adaptation",
    )
    field_data_types_to_exclude: list[str] | None = PydanticField(
        default=None,
        description="List of data types to exclude from adaptation",
    )
    field_characterisations_to_exclude: list[str] | None = PydanticField(
        default=None,
        description="List of characterisations to exclude from adaptation",
    )
    exclude_fields_without_characterisations: bool = PydanticField(
        default=False,
        description="Whether to exclude fields without characterisations",
    )

    def adapt_field(
        self,
        original_field: Field,
        field_naming_mapping: FieldNamingMapping | None = None,
        field_catalog: dict[str, Field] | None = None,
    ) -> Field:
        if field_naming_mapping is None:
            field_naming_mapping = FieldNamingMapping()
        if field_catalog is None:
            field_catalog = {}
        if field_naming_mapping.has_specific_naming_rule(original_field.name):
            return self.create_new_field(
                original_field,
                override_params={
                    "field_name": field_naming_mapping.get_target_field_name(
                        original_field.name
                    )
                },
            )
        else:
            field_name_override = field_naming_mapping.get_target_field_name(
                original_field.name
            )
            if field_name_override in field_catalog.keys():
                return self.create_new_field(field_catalog[field_name_override])
            else:
                return self.create_new_field(
                    original_field,
                    override_params={
                        "field_name": field_naming_mapping.get_target_field_name(
                            original_field.name
                        )
                    },
                )

    def get_orig_to_new_characterisation_mapping(self) -> dict[str, str]:
        return (
            self.orig_to_new_characterisation_mapping
            if self.orig_to_new_characterisation_mapping is not None
            else {}
        )

    def get_field_names_to_exclude(self) -> list[str]:
        return (
            self.field_names_to_exclude
            if self.field_names_to_exclude is not None
            else []
        )

    def get_field_data_types_to_exclude(self) -> list[str]:
        return (
            self.field_data_types_to_exclude
            if self.field_data_types_to_exclude is not None
            else []
        )

    def get_field_characterisations_to_exclude(self) -> list[str]:
        """Returns lowercase list of characterisations to exclude."""
        if self.field_characterisations_to_exclude is None:
            return []
        return [char.lower() for char in self.field_characterisations_to_exclude]

    def should_field_be_adapted(self, field: Field) -> bool:
        excluded_chars = self.get_field_characterisations_to_exclude()
        field_char_names = [char.lower() for char in field.get_characterisation_names()]
        has_excluded_char = any(char in excluded_chars for char in field_char_names)
        if (
            (field.name not in self.get_field_names_to_exclude())
            & (field.data_type not in self.get_field_data_types_to_exclude())
            & (not has_excluded_char)
            & (
                (not self.exclude_fields_without_characterisations)
                | (field.has_characterisations())
            )
        ):
            return True
        return False

    def create_new_field(
        self, original_field: Field, override_params: dict[str, str] | None = None
    ) -> Field:
        """Creates a field based on this template."""
        if override_params is None:
            override_params = {}
        new_characterisations = []
        if original_field.characterisations is not None:
            for characterisation in original_field.characterisations:
                if (
                    characterisation.characterisation
                    == FieldCharacterisationDefinitionNames.MANDATORY
                ):
                    if not self.all_fields_optional:
                        new_characterisations.append(
                            FieldCharacterisation.create_from_definition(
                                FieldCharacterisationDefinitions.MANDATORY
                            )
                        )
                elif characterisation.characterisation in list(
                    self.get_orig_to_new_characterisation_mapping().keys()
                ):
                    tgt_characterisation_name = (
                        self.get_orig_to_new_characterisation_mapping()[
                            characterisation.characterisation
                        ]
                    )
                    new_characterisations.append(
                        FieldCharacterisation(
                            name=tgt_characterisation_name,
                            characterisation=tgt_characterisation_name,
                            attributes=None,
                        )
                    )
                else:
                    new_characterisations.append(characterisation)

        new_field_format = (
            self.field_format_adapter.get_adapted_field_format(
                data_type=original_field.data_type,
                length=original_field.length,
                precision=original_field.precision,
                characterisations=original_field.get_characterisation_names(),
            )
            if self.field_format_adapter is not None
            else (
                original_field.data_type,
                original_field.length,
                original_field.precision,
            )
        )

        original_field_dict = original_field.to_dict()

        creation_param_dict: dict[str, Any] = {}
        creation_param_dict["original_field"] = original_field_dict
        creation_param_dict["override_params"] = (
            override_params if override_params is not None else {}
        )

        short_description = None
        if self.short_description_rule is not None:
            short_description = render_template_with_none_return_allowed(
                self.short_description_rule, **creation_param_dict
            )

        return Field(
            name=render_template(self.name_rule, **creation_param_dict),
            description=render_template_with_none_return_allowed(
                self.description_rule, **creation_param_dict
            ),
            short_description=short_description,
            data_type=new_field_format[0],
            length=new_field_format[1],
            precision=new_field_format[2],
            default_value=original_field.default_value,
            characterisations=new_characterisations,
        )


class NamespacedFieldAdapter(NldNamespacedBaseModelWrapper[FieldAdapter]):
    """FieldAdapter wrapped with namespace information."""
