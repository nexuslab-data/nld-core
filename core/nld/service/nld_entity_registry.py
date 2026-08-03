from nld.business import (
    BusinessDictionary,
    NamespacedBusinessDictionary,
)
from nld.flow.definition.flow_definition import (
    DataFlowDefinition,
    NamespacedDataFlowDefinition,
)
from nld.governance.ownership import (
    FlowOwner,
    NamespacedFlowOwner,
    NamespacedStructureOwner,
    StructureOwner,
)
from nld.scheduling import (
    FlowTask,
    NamespacedFlowTaskModel,
)
from nld.structure import StructureAudit, StructureModel
from nld.structure.audit.structure_audit import NamespacedStructureAudit
from nld.structure.field import FieldTemplate
from nld.structure.field.field import Field, NamespacedField, NamespacedFieldTemplate
from nld.structure.field.field_adapter import FieldAdapter, NamespacedFieldAdapter
from nld.structure.field.field_characterisation_definition import (
    FieldCharacterisationDefinition,
    NamespacedFieldCharacterisationDefinition,
)
from nld.structure.field.field_format_adapter import (
    FieldFormatAdapter,
    NamespacedFieldFormatAdapter,
)
from nld.structure.structure import (
    NamespacedStructureTemplate,
    Structure,
    StructureAdapter,
    StructureTemplate,
)
from nld.structure.structure.structure import NamespacedStructure
from nld.structure.structure.structure_adapter import NamespacedStructureAdapter
from nld.structure.structure_model.structure_model import (
    NamespacedStructureModel,
)

from .entity_definition import (
    ENTITY_CATEGORY_DATA_FLOW,
    ENTITY_CATEGORY_GOVERNANCE,
    ENTITY_CATEGORY_STRUCTURE,
    ENTITY_CATEGORY_STRUCTURE_CONFIGURATION,
    ENTITY_CATEGORY_VOCABULARY,
    EntityDefinition,
)
from .entity_provider import EntityProvider


class EntityTypeNames:
    """Centralized entity type name constants."""

    # Model entities
    FIELD = "field"
    FIELD_ADAPTER = "field_adapter"
    FIELD_CHARACTERISATION_DEFINITION = "field_characterisation_definition"
    FIELD_FORMAT_ADAPTER = "field_format_adapter"
    FIELD_TEMPLATE = "field_template"
    STRUCTURE_ADAPTER = "structure_adapter"
    STRUCTURE_TEMPLATE = "structure_template"

    # Structure entities
    STRUCTURE = "structure"
    STRUCTURE_MODEL = "structure_model"
    STRUCTURE_AUDIT = "structure_audit"

    # Data Flow entities
    DATA_FLOW_DEFINITION = "flows"
    FLOW_TASK = "scheduling"

    # Vocabulary entities
    BUSINESS_DICTIONARY = "business_dictionary"

    # Governance entities
    STRUCTURE_OWNER = "structure_owner"
    FLOW_OWNER = "flow_owner"


# Define all entity definitions
ALL_ENTITY_DEFINITIONS = [
    # Structure configuration entities - search parents (inherit from root)
    # Ordered by dependency: base fields first, then templates, then adapters
    EntityDefinition(
        name=EntityTypeNames.FIELD,
        model_type=Field,
        folder_name=f"templates/{EntityTypeNames.FIELD}",
        category=ENTITY_CATEGORY_STRUCTURE,
        display_name="Field",
    ),
    EntityDefinition(
        name=EntityTypeNames.FIELD_ADAPTER,
        model_type=FieldAdapter,
        folder_name=f"templates/{EntityTypeNames.FIELD_ADAPTER}",
        search_direction="parents",
        category=ENTITY_CATEGORY_STRUCTURE_CONFIGURATION,
        display_name="Field Adapter",
    ),
    EntityDefinition(
        name=EntityTypeNames.FIELD_CHARACTERISATION_DEFINITION,
        model_type=FieldCharacterisationDefinition,
        folder_name="characterisations/field",
        search_direction="parents",
        category=ENTITY_CATEGORY_STRUCTURE_CONFIGURATION,
        display_name="Field Characterisation Definition",
    ),
    EntityDefinition(
        name=EntityTypeNames.FIELD_FORMAT_ADAPTER,
        model_type=FieldFormatAdapter,
        folder_name=f"templates/{EntityTypeNames.FIELD_FORMAT_ADAPTER}",
        search_direction="parents",
        category=ENTITY_CATEGORY_STRUCTURE_CONFIGURATION,
        display_name="Field Format Adapter",
    ),
    EntityDefinition(
        name=EntityTypeNames.FIELD_TEMPLATE,
        model_type=FieldTemplate,
        folder_name=f"templates/{EntityTypeNames.FIELD_TEMPLATE}",
        search_direction="parents",
        category=ENTITY_CATEGORY_STRUCTURE_CONFIGURATION,
        display_name="Field Template",
    ),
    EntityDefinition(
        name=EntityTypeNames.STRUCTURE_ADAPTER,
        model_type=StructureAdapter,
        folder_name=f"templates/{EntityTypeNames.STRUCTURE_ADAPTER}",
        search_direction="parents",
        category=ENTITY_CATEGORY_STRUCTURE_CONFIGURATION,
        display_name="Structure Adapter",
    ),
    EntityDefinition(
        name=EntityTypeNames.STRUCTURE_TEMPLATE,
        model_type=StructureTemplate,
        folder_name=f"templates/{EntityTypeNames.STRUCTURE_TEMPLATE}",
        search_direction="parents",
        category=ENTITY_CATEGORY_STRUCTURE_CONFIGURATION,
        display_name="Structure Template",
    ),
    # Structure entities - search children (default)
    EntityDefinition(
        name=EntityTypeNames.STRUCTURE,
        model_type=Structure,
        folder_name="structure",
        category=ENTITY_CATEGORY_STRUCTURE,
        display_name="Structure",
    ),
    EntityDefinition(
        name=EntityTypeNames.STRUCTURE_MODEL,
        model_type=StructureModel,
        folder_name="structure_model",
        category=ENTITY_CATEGORY_STRUCTURE,
        display_name="Structure Model",
    ),
    EntityDefinition(
        name=EntityTypeNames.STRUCTURE_AUDIT,
        model_type=StructureAudit,
        folder_name="audits/structure",
        category=ENTITY_CATEGORY_STRUCTURE,
        display_name="Structure Audit",
    ),
    # Data Flow entities - search children (default)
    EntityDefinition(
        name=EntityTypeNames.DATA_FLOW_DEFINITION,
        model_type=DataFlowDefinition,
        folder_name=f"{EntityTypeNames.DATA_FLOW_DEFINITION}",
        category=ENTITY_CATEGORY_DATA_FLOW,
        display_name="Data Flow Definition",
    ),
    EntityDefinition(
        name=EntityTypeNames.FLOW_TASK,
        model_type=FlowTask,
        folder_name=f"{EntityTypeNames.FLOW_TASK}",
        category=ENTITY_CATEGORY_DATA_FLOW,
        display_name="Flow Task",
    ),
    # Vocabulary entities - inherit from parent namespaces with nearest override
    EntityDefinition(
        name=EntityTypeNames.BUSINESS_DICTIONARY,
        model_type=BusinessDictionary,
        folder_name="business/dictionary",
        search_direction="parents",
        category=ENTITY_CATEGORY_VOCABULARY,
        display_name="Business Dictionary",
    ),
    # Governance entities - inherit from parent namespaces with nearest override
    EntityDefinition(
        name=EntityTypeNames.STRUCTURE_OWNER,
        model_type=StructureOwner,
        folder_name="governance/structure",
        search_direction="parents",
        category=ENTITY_CATEGORY_GOVERNANCE,
        display_name="Structure Owner",
    ),
    EntityDefinition(
        name=EntityTypeNames.FLOW_OWNER,
        model_type=FlowOwner,
        folder_name="governance/flow",
        search_direction="parents",
        category=ENTITY_CATEGORY_GOVERNANCE,
        display_name="Flow Owner",
    ),
]


class NldEntityRegistry(EntityProvider):
    """Centralized Entity Registry.

    Manages all entities in a unified registry instead of separate services
    and provides convenience methods for accessing entities by type.
    """

    def __init__(
        self,
        additional_entity_definitions: list[EntityDefinition] | None = None,
    ) -> None:
        additional_entity_definitions = (
            additional_entity_definitions
            if additional_entity_definitions is not None
            else []
        )
        super().__init__(
            entity_definitions=[
                *ALL_ENTITY_DEFINITIONS,
                *additional_entity_definitions,
            ],
        )

    def load_entities(
        self,
        root_directory: str,
        fail_on_missing_folder: bool = False,
        force_reload: bool = False,
        requested_entity_definitions: list[EntityDefinition] | None = None,
    ) -> None:
        """Load entities, always including ``always_load`` entity types.

        A selective load (``requested_entity_definitions`` set) restricts loading
        to the requested types and their dependencies. Entity types flagged
        ``always_load`` (e.g. project additional entities, resolved by key from
        tasks regardless of the requested scope) must load even then, so they are
        unioned into the requested set before delegating to the base loader. A
        full load (``requested_entity_definitions=None``) already loads them.
        """
        if requested_entity_definitions is not None:
            requested_names = {
                definition.name for definition in requested_entity_definitions
            }
            requested_entity_definitions = [
                *requested_entity_definitions,
                *(
                    definition
                    for definition in self.entity_definitions
                    if definition.always_load and definition.name not in requested_names
                ),
            ]
        super().load_entities(
            root_directory=root_directory,
            fail_on_missing_folder=fail_on_missing_folder,
            force_reload=force_reload,
            requested_entity_definitions=requested_entity_definitions,
        )

    # Field methods
    def get_field_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedField]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.FIELD,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedField(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_field_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.FIELD,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_field_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.FIELD,
            namespace=namespace,
        )

    def get_field(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedField:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.FIELD,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedField(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    def get_fields(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> list[NamespacedField]:
        wrappers = self.get_entities(
            entity_type=EntityTypeNames.FIELD,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return [
            NamespacedField(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for wrapper in wrappers
        ]

    def get_fields_as_dict(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> dict[str, NamespacedField]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.FIELD,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedField(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    # Field Adapter methods
    def get_field_adapter_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedFieldAdapter]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.FIELD_ADAPTER,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedFieldAdapter(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_field_adapter_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.FIELD_ADAPTER,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_field_adapter_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.FIELD_ADAPTER,
            namespace=namespace,
        )

    def get_field_adapter(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedFieldAdapter:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.FIELD_ADAPTER,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedFieldAdapter(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    def get_field_adapters(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> list[NamespacedFieldAdapter]:
        wrappers = self.get_entities(
            entity_type=EntityTypeNames.FIELD_ADAPTER,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return [
            NamespacedFieldAdapter(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for wrapper in wrappers
        ]

    def get_field_adapters_as_dict(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> dict[str, NamespacedFieldAdapter]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.FIELD_ADAPTER,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedFieldAdapter(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    # Field Characterisation Definition methods
    def get_field_characterisation_definition_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedFieldCharacterisationDefinition]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.FIELD_CHARACTERISATION_DEFINITION,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedFieldCharacterisationDefinition(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_field_characterisation_definition_keys(
        self, namespace: str | None = None
    ) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.FIELD_CHARACTERISATION_DEFINITION,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_field_characterisation_definition_keys(
        self, namespace: str | None = None
    ) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.FIELD_CHARACTERISATION_DEFINITION,
            namespace=namespace,
        )

    def get_field_characterisation_definition(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedFieldCharacterisationDefinition:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.FIELD_CHARACTERISATION_DEFINITION,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedFieldCharacterisationDefinition(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    # Field Format Adapter methods
    def get_field_format_adapter_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedFieldFormatAdapter]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.FIELD_FORMAT_ADAPTER,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedFieldFormatAdapter(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_field_format_adapter_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.FIELD_FORMAT_ADAPTER,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_field_format_adapter_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.FIELD_FORMAT_ADAPTER,
            namespace=namespace,
        )

    def get_field_format_adapter(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedFieldFormatAdapter:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.FIELD_FORMAT_ADAPTER,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedFieldFormatAdapter(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    def get_field_format_adapters(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> list[NamespacedFieldFormatAdapter]:
        wrappers = self.get_entities(
            entity_type=EntityTypeNames.FIELD_FORMAT_ADAPTER,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return [
            NamespacedFieldFormatAdapter(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for wrapper in wrappers
        ]

    def get_field_format_adapters_as_dict(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> dict[str, NamespacedFieldFormatAdapter]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.FIELD_FORMAT_ADAPTER,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedFieldFormatAdapter(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    # Field Template methods
    def get_field_template_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedFieldTemplate]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.FIELD_TEMPLATE,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedFieldTemplate(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_field_template_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.FIELD_TEMPLATE,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_field_template_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.FIELD_TEMPLATE,
            namespace=namespace,
        )

    def get_field_template(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedFieldTemplate:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.FIELD_TEMPLATE,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedFieldTemplate(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    def get_field_templates(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> list[NamespacedFieldTemplate]:
        wrappers = self.get_entities(
            entity_type=EntityTypeNames.FIELD_TEMPLATE,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return [
            NamespacedFieldTemplate(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for wrapper in wrappers
        ]

    def get_field_templates_as_dict(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> dict[str, NamespacedFieldTemplate]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.FIELD_TEMPLATE,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedFieldTemplate(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    # Structure Adapter methods
    def get_structure_adapter_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedStructureAdapter]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.STRUCTURE_ADAPTER,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedStructureAdapter(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_structure_adapter_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.STRUCTURE_ADAPTER,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_structure_adapter_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.STRUCTURE_ADAPTER,
            namespace=namespace,
        )

    def get_structure_adapter(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedStructureAdapter:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.STRUCTURE_ADAPTER,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedStructureAdapter(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    def get_structure_adapters(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> list[NamespacedStructureAdapter]:
        wrappers = self.get_entities(
            entity_type=EntityTypeNames.STRUCTURE_ADAPTER,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return [
            NamespacedStructureAdapter(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for wrapper in wrappers
        ]

    def get_structure_adapters_as_dict(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> dict[str, NamespacedStructureAdapter]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.STRUCTURE_ADAPTER,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedStructureAdapter(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    # Structure Template methods
    def get_structure_template_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedStructureTemplate]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.STRUCTURE_TEMPLATE,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedStructureTemplate(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_structure_template_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.STRUCTURE_TEMPLATE,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_structure_template_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.STRUCTURE_TEMPLATE,
            namespace=namespace,
        )

    def get_structure_template(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedStructureTemplate:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.STRUCTURE_TEMPLATE,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedStructureTemplate(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    def get_structure_templates(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> list[NamespacedStructureTemplate]:
        wrappers = self.get_entities(
            entity_type=EntityTypeNames.STRUCTURE_TEMPLATE,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return [
            NamespacedStructureTemplate(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for wrapper in wrappers
        ]

    def get_structure_templates_as_dict(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> dict[str, NamespacedStructureTemplate]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.STRUCTURE_TEMPLATE,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedStructureTemplate(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    # Structure methods
    def get_structure_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedStructure]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.STRUCTURE,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedStructure(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_structure_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.STRUCTURE,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_structure_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.STRUCTURE,
            namespace=namespace,
        )

    def get_structure(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedStructure:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.STRUCTURE,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedStructure(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    def get_structures(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> list[NamespacedStructure]:
        wrappers = self.get_entities(
            entity_type=EntityTypeNames.STRUCTURE,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return [
            NamespacedStructure(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for wrapper in wrappers
        ]

    def get_structures_as_dict(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> dict[str, NamespacedStructure]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.STRUCTURE,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedStructure(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    # Structure Model methods
    def get_structure_model_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedStructureModel]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.STRUCTURE_MODEL,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedStructureModel(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_structure_model_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.STRUCTURE_MODEL,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_structure_model_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.STRUCTURE_MODEL,
            namespace=namespace,
        )

    def get_structure_model(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedStructureModel:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.STRUCTURE_MODEL,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedStructureModel(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    def get_structure_models(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> list[NamespacedStructureModel]:
        wrappers = self.get_entities(
            entity_type=EntityTypeNames.STRUCTURE_MODEL,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return [
            NamespacedStructureModel(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for wrapper in wrappers
        ]

    def get_structure_models_as_dict(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> dict[str, NamespacedStructureModel]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.STRUCTURE_MODEL,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedStructureModel(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    # Structure Audit methods
    def get_structure_audit_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedStructureAudit]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.STRUCTURE_AUDIT,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedStructureAudit(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_structure_audit_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.STRUCTURE_AUDIT,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_structure_audit_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.STRUCTURE_AUDIT,
            namespace=namespace,
        )

    def get_structure_audit(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedStructureAudit:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.STRUCTURE_AUDIT,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedStructureAudit(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    # DataFlow methods
    def get_data_flow_definition_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedDataFlowDefinition]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.DATA_FLOW_DEFINITION,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedDataFlowDefinition(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_data_flow_definition_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.DATA_FLOW_DEFINITION,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_data_flow_definition_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.DATA_FLOW_DEFINITION,
            namespace=namespace,
        )

    def get_data_flow_definition(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedDataFlowDefinition:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.DATA_FLOW_DEFINITION,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedDataFlowDefinition(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    def get_data_flow_definitions(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> list[NamespacedDataFlowDefinition]:
        wrappers = self.get_entities(
            entity_type=EntityTypeNames.DATA_FLOW_DEFINITION,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return [
            NamespacedDataFlowDefinition(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for wrapper in wrappers
        ]

    def get_data_flow_definitions_as_dict(
        self, entity_keys: list[str], namespace: str | None = None
    ) -> dict[str, NamespacedDataFlowDefinition]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.DATA_FLOW_DEFINITION,
            entity_keys=entity_keys,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedDataFlowDefinition(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    # Flow Task methods
    def get_flow_task_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedFlowTaskModel]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.FLOW_TASK,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedFlowTaskModel(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_flow_task_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.FLOW_TASK,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_flow_task_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.FLOW_TASK,
            namespace=namespace,
        )

    def get_flow_task(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedFlowTaskModel:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.FLOW_TASK,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedFlowTaskModel(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    # Business Dictionary methods
    def get_business_dictionary_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedBusinessDictionary]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.BUSINESS_DICTIONARY,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedBusinessDictionary(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_business_dictionary_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.BUSINESS_DICTIONARY,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_business_dictionary_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.BUSINESS_DICTIONARY,
            namespace=namespace,
        )

    def get_business_dictionary(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedBusinessDictionary:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.BUSINESS_DICTIONARY,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedBusinessDictionary(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    # Structure Owner methods
    def get_structure_owner_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedStructureOwner]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.STRUCTURE_OWNER,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedStructureOwner(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_structure_owner_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.STRUCTURE_OWNER,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_structure_owner_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.STRUCTURE_OWNER,
            namespace=namespace,
        )

    def get_structure_owner(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedStructureOwner:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.STRUCTURE_OWNER,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedStructureOwner(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )

    # Flow Owner methods
    def get_flow_owner_dict(
        self, namespace: str | None = None
    ) -> dict[str, NamespacedFlowOwner]:
        wrappers_dict = self.get_entities_as_dict(
            entity_type=EntityTypeNames.FLOW_OWNER,
            namespace=namespace,
            use_search_direction=True,
        )
        return {
            key: NamespacedFlowOwner(
                model=wrapper.model,
                namespace=wrapper.namespace,
            )
            for key, wrapper in wrappers_dict.items()
        }

    def get_flow_owner_keys(self, namespace: str | None = None) -> list[str]:
        return self.get_entity_keys(
            entity_type=EntityTypeNames.FLOW_OWNER,
            namespace=namespace,
            use_search_direction=True,
        )

    def list_flow_owner_keys(self, namespace: str | None = None) -> list[str]:
        return self.list_entity_keys(
            entity_type=EntityTypeNames.FLOW_OWNER,
            namespace=namespace,
        )

    def get_flow_owner(
        self, entity_key: str, namespace: str | None = None
    ) -> NamespacedFlowOwner:
        wrapper = self.get_entity(
            entity_type=EntityTypeNames.FLOW_OWNER,
            entity_key=entity_key,
            namespace=namespace,
            use_search_direction=True,
        )
        return NamespacedFlowOwner(
            model=wrapper.model,
            namespace=wrapper.namespace,
        )
