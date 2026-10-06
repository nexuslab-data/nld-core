import difflib
import os
from typing import Any

from nld.connector.base import resolve_sqlglot_dialect
from nld.flow.definition import (
    DataFlowStructurePredecessor,
    NamespacedDataFlowDefinition,
)
from nld.flow.sql.sql_file_resolver import (
    load_sql_file_content,
    try_resolve_sql_file_path,
)
from nld.flow.structure_generation.exceptions import StructureGenerationException
from nld.flow.structure_generation.projection import (
    ProjectedField,
    StructureProjection,
    resolve_projection,
)
from nld.flow.utils import FlowUpdateStrategies
from nld.pydantic import NldBaseModel, NldEntityLayout, NldNamespace
from nld.service import EntityTypeNames, NldEntityRegistry
from nld.structure import (
    Field,
    FieldDataType,
    NamespacedStructure,
    Structure,
    StructureGenerationMetadata,
)
from nld.utils.mixin import NldMixIn
from nld.utils.yaml_util import (
    dump_dict_to_entity_yaml_str,
    load_yaml_file_into_dict,
)

STRUCTURE_FOLDER_NAME: str = "structure"

# Field keys rewritten from the source on every generation. Every other
# field key keeps its existing value, filled from the source when missing.
GENERATOR_OWNED_FIELD_KEYS: tuple[str, ...] = (
    "data_type",
    "length",
    "precision",
    "fields",
)


class GenerationInputs(NldBaseModel):
    """Everything a generation reads, resolved from one flow definition."""

    flow_id: str
    predecessor_reference: str
    projection: StructureProjection
    source_structure: Structure
    target_name: str
    target_namespace: str
    write_strategy: str | None = None

    @property
    def target_id(self) -> str:
        """The target structure as <namespace>.<name>."""
        if NldNamespace(self.target_namespace).is_root:
            return self.target_name
        return f"{self.target_namespace}.{self.target_name}"


class StructureGenerationResult(NldBaseModel):
    """The outcome of generating one structure, before or after writing it."""

    changes: list[str] = []
    existing_content: dict[str, Any] | None = None
    file_path: str
    flow_id: str
    generated_content: dict[str, Any]
    structure_id: str
    warnings: list[str] = []

    def is_up_to_date(self) -> bool:
        """Whether the file on disk already holds the generated content."""
        return self.existing_content == self.generated_content

    def is_new(self) -> bool:
        """Whether the structure file does not exist yet."""
        return self.existing_content is None

    def render_diff(self) -> str:
        """Render a unified diff between the file and the generated content.

        Both sides go through the same YAML dumper, so formatting-only
        differences of the file on disk never show up.
        """
        before = (
            dump_dict_to_entity_yaml_str(self.existing_content)
            if self.existing_content is not None
            else ""
        )
        after = dump_dict_to_entity_yaml_str(self.generated_content)
        return "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"{self.file_path} (current)",
                tofile=f"{self.file_path} (generated)",
            ),
        )


class TargetStructureGenerator(NldMixIn):
    """Generate a flow's target structure YAML from its single predecessor.

    The structure always lives as a named YAML file in the project. The
    generator writes it on first use, then merges every regeneration into
    the existing file: the field list, field types, nested fields and the
    ``generation_metadata`` provenance are rewritten from the source. Field
    attributes such as descriptions and characterisations keep their value
    and are only filled from the source when missing. Structure-level
    attributes (description, properties, tags, characterisations, hooks)
    are seeded on the first generation, then owned by the user; source
    templates missing from the file are added to it.

    Example:
        >>> generator = TargetStructureGenerator(
        ...     entities_root_folder_path=project.entities_root_folder_path,
        ...     entity_layout=project.entity_layout,
        ...     entity_registry=project.entity_registry,
        ... )
        >>> result = generator.generate(namespaced_flow=namespaced_flow)
        >>> generator.write(result=result)
    """

    def __init__(
        self,
        entities_root_folder_path: str,
        entity_layout: NldEntityLayout,
        entity_registry: NldEntityRegistry,
    ) -> None:
        super().__init__()
        self.entities_root_folder_path = entities_root_folder_path
        self.entity_layout = entity_layout
        self.entity_registry = entity_registry

    def generate(
        self,
        namespaced_flow: NamespacedDataFlowDefinition,
    ) -> StructureGenerationResult:
        """Compute the structure content of a flow target, without writing it.

        Raises:
            StructureGenerationException: when the flow does not have exactly
                one predecessor, or its projection cannot be resolved.
        """
        inputs = self.resolve_inputs(namespaced_flow=namespaced_flow)
        file_path = self._resolve_structure_file_path(
            target_name=inputs.target_name,
            target_namespace=inputs.target_namespace,
        )
        existing_content = (
            load_yaml_file_into_dict(file_path) if os.path.isfile(file_path) else None
        )
        if existing_content is not None and not isinstance(existing_content, dict):
            raise StructureGenerationException(
                f"Structure file '{file_path}' does not hold a YAML mapping"
            )

        warnings: list[str] = []
        generated_content = self._build_content(
            existing_content=existing_content,
            inputs=inputs,
            warnings=warnings,
        )
        return StructureGenerationResult(
            changes=self._summarize_changes(
                existing_content=existing_content,
                generated_content=generated_content,
            ),
            existing_content=existing_content,
            file_path=file_path,
            flow_id=inputs.flow_id,
            generated_content=generated_content,
            structure_id=inputs.target_id,
            warnings=warnings,
        )

    def write(self, result: StructureGenerationResult) -> bool:
        """Write the generated content, returning False when already up to date.

        An up-to-date file is left untouched, so its comments and formatting
        survive a regeneration that changes nothing.
        """
        if result.is_up_to_date():
            return False
        os.makedirs(
            os.path.dirname(result.file_path),
            exist_ok=True,
        )
        with open(
            result.file_path,
            "w",
            encoding="utf-8",
        ) as structure_file:
            structure_file.write(
                dump_dict_to_entity_yaml_str(result.generated_content),
            )
        return True

    def find_staleness_issues(
        self,
        namespaced_structure: NamespacedStructure,
    ) -> list[str]:
        """List why a generated structure no longer matches its flow.

        Regenerates the structure in memory from the flow named in its
        ``generation_metadata`` and compares the result with the structure
        file, so any change of the source structure or of the flow
        projection that would change the file is reported. Returns an empty
        list for an up-to-date or a non-generated structure.
        """
        generation_metadata = namespaced_structure.model.generation_metadata
        if generation_metadata is None:
            return []

        flow_namespace, flow_name = split_entity_id(
            entity_id=generation_metadata.flow,
        )
        try:
            namespaced_flow = self.entity_registry.get_data_flow_definition(
                entity_key=flow_name,
                namespace=flow_namespace,
            )
            result = self.generate(namespaced_flow=namespaced_flow)
        except Exception as error:
            return [
                f"its flow '{generation_metadata.flow}' cannot be regenerated: {error}"
            ]
        if result.is_up_to_date():
            return []
        return [
            f"regenerating it from flow '{generation_metadata.flow}' would change "
            f"it ({'; '.join(result.changes)})"
        ]

    def resolve_inputs(
        self,
        namespaced_flow: NamespacedDataFlowDefinition,
    ) -> GenerationInputs:
        """Resolve the source structure, projection and target of a flow."""
        flow_definition = namespaced_flow.model
        flow_namespace = str(namespaced_flow.namespace)
        predecessor_key, predecessor = self._resolve_single_predecessor(
            namespaced_flow=namespaced_flow,
        )
        source_structure: Structure = predecessor.full_path.resolve(
            entity_type=EntityTypeNames.STRUCTURE,
        )

        sql_file_path = try_resolve_sql_file_path(
            entities_root_folder_path=self.entities_root_folder_path,
            namespace=flow_namespace,
            flow_name=flow_definition.name,
            entity_layout=self.entity_layout,
        )
        projection = resolve_projection(
            flow_definition=flow_definition,
            predecessor_key=predecessor_key,
            source_structure=source_structure,
            sql_content=(
                load_sql_file_content(sql_file_path)
                if sql_file_path is not None
                else None
            ),
            dialect=(
                resolve_sqlglot_dialect(source_structure.connector_type)
                if source_structure.connector_type is not None
                else None
            ),
        )

        if flow_definition.target_structure is not None:
            target_namespace = str(flow_definition.target_structure.namespace)
            target_name = flow_definition.target_structure.entity_name
        else:
            target_namespace = flow_namespace
            target_name = flow_definition.name

        return GenerationInputs(
            flow_id=namespaced_flow.id,
            predecessor_reference=str(predecessor.full_path),
            projection=projection,
            source_structure=source_structure,
            target_name=target_name,
            target_namespace=target_namespace,
            write_strategy=flow_definition.write_strategy,
        )

    def _resolve_single_predecessor(
        self,
        namespaced_flow: NamespacedDataFlowDefinition,
    ) -> tuple[str, DataFlowStructurePredecessor]:
        """Return the only predecessor of the flow, or raise."""
        predecessors = namespaced_flow.model.predecessors
        if len(predecessors) != 1:
            raise StructureGenerationException(
                f"Flow '{namespaced_flow.id}' has {len(predecessors)} "
                f"predecessor(s): generating its target structure needs exactly one"
            )
        return next(iter(predecessors.items()))

    def _resolve_structure_file_path(
        self,
        target_name: str,
        target_namespace: str,
    ) -> str:
        """Return the existing structure file, or where to create it."""
        structure_directory = self.entity_layout.get_entity_directory(
            entities_root_folder_path=self.entities_root_folder_path,
            entity_folder_name=STRUCTURE_FOLDER_NAME,
            namespace=target_namespace,
        )
        for extension in (".yml", ".yaml"):
            candidate_path = os.path.join(
                structure_directory,
                f"{target_name}{extension}",
            )
            if os.path.isfile(candidate_path):
                return candidate_path
        return os.path.join(
            structure_directory,
            f"{target_name}.yml",
        )

    def _build_content(
        self,
        existing_content: dict[str, Any] | None,
        inputs: GenerationInputs,
        warnings: list[str],
    ) -> dict[str, Any]:
        """Build the structure content, merged into the existing one if any."""
        source_structure = inputs.source_structure
        projection = inputs.projection

        seeded_templates = self._select_source_templates(
            projection=projection,
            source_structure=source_structure,
        )
        existing_templates = (
            existing_content.get("templates") or []
            if existing_content is not None
            else []
        )
        existing_template_names = [
            _get_template_name(template) for template in existing_templates
        ]
        templates: list[Any] = list(existing_templates) + [
            template_name
            for template_name in seeded_templates
            if template_name not in existing_template_names
        ]
        template_field_names = self._collect_template_field_names(
            target_namespace=inputs.target_namespace,
            templates=templates,
            warnings=warnings,
        )

        existing_fields: dict[str, Any] = (
            existing_content.get("fields") or {} if existing_content is not None else {}
        )
        fields = self._build_fields(
            existing_fields=existing_fields,
            projection=projection,
            source_structure=source_structure,
            structure_id=inputs.target_id,
            template_field_names=template_field_names,
        )

        projected_names = set(projection.get_field_names())
        for template_field_name in sorted(template_field_names - projected_names):
            warnings.append(
                f"A template of '{inputs.target_id}' provides field "
                f"'{template_field_name}', which the flow does not select"
            )

        generation_metadata = StructureGenerationMetadata(
            flow=inputs.flow_id,
            source=inputs.predecessor_reference,
        ).to_dict()
        structure_type = (
            "VIEW"
            if (inputs.write_strategy or "").upper() == FlowUpdateStrategies.VIEW
            else "TABLE"
        )

        if existing_content is None:
            content = self._build_seeded_content(
                fields=fields,
                generation_metadata=generation_metadata,
                projection=projection,
                source_structure=source_structure,
                structure_name=inputs.target_name,
                structure_type=structure_type,
                templates=templates,
            )
        else:
            content = {"generation_metadata": generation_metadata}
            for key, value in existing_content.items():
                if key == "generation_metadata":
                    continue
                if key == "structure_type":
                    content[key] = structure_type
                elif key == "fields":
                    content[key] = fields
                elif key == "templates":
                    content[key] = templates
                else:
                    content[key] = value
            if "structure_type" not in content:
                content["structure_type"] = structure_type
            if templates and "templates" not in content:
                content["templates"] = templates
            if "fields" not in content:
                content["fields"] = fields

        self._check_characterisation_links(
            content=content,
            available_field_names=set(fields) | template_field_names,
            structure_id=inputs.target_id,
            warnings=warnings,
        )
        return content

    def _build_seeded_content(
        self,
        fields: dict[str, Any],
        generation_metadata: dict[str, Any],
        projection: StructureProjection,
        source_structure: Structure,
        structure_name: str,
        structure_type: str,
        templates: list[Any],
    ) -> dict[str, Any]:
        """Build a brand-new structure, seeding user-owned keys from the source."""
        content: dict[str, Any] = {
            "generation_metadata": generation_metadata,
            "structure_type": structure_type,
        }
        if source_structure.connector_type is not None:
            content["connector_type"] = source_structure.connector_type
        if source_structure.description:
            content["description"] = source_structure.description
        if source_structure.properties:
            content["properties"] = dict(source_structure.properties)
        if templates:
            content["templates"] = templates
        content["fields"] = fields
        characterisations = self._seed_structure_characterisations(
            projection=projection,
            source_structure=source_structure,
            structure_name=structure_name,
        )
        if characterisations:
            content["characterisations"] = characterisations
        return content

    def _select_source_templates(
        self,
        projection: StructureProjection,
        source_structure: Structure,
    ) -> list[str]:
        """Keep the source templates whose fields are all passed through as is.

        A template is reused only when every field it provides is selected
        under its own name and type; otherwise its selected fields are
        written as explicit fields instead.
        """
        passthrough_names = {
            projected_field.name
            for projected_field in projection.fields
            if _is_plain_passthrough(projected_field)
        }
        template_names: list[str] = []
        for template in source_structure.templates:
            template_field_names = {
                field_template.get_field_instance().name
                for field_template in template.field_templates
            }
            if template_field_names <= passthrough_names:
                template_names.append(template.name)
        return template_names

    def _collect_template_field_names(
        self,
        target_namespace: str,
        templates: list[Any],
        warnings: list[str],
    ) -> set[str]:
        """Collect the names of every field provided by the given templates."""
        field_names: set[str] = set()
        for template in templates:
            template_name = _get_template_name(template)
            try:
                structure_template = self.entity_registry.get_structure_template(
                    entity_key=template_name,
                    namespace=target_namespace,
                ).model
            except Exception:
                warnings.append(
                    f"Structure template '{template_name}' cannot be resolved: "
                    f"its fields are not taken into account"
                )
                continue
            field_names.update(
                field_template.get_field_instance().name
                for field_template in structure_template.field_templates
            )
        return field_names

    def _build_fields(
        self,
        existing_fields: dict[str, Any],
        projection: StructureProjection,
        source_structure: Structure,
        structure_id: str,
        template_field_names: set[str],
    ) -> dict[str, Any]:
        """Build the explicit fields, merging the user-owned attributes back.

        A passed-through field that a template provides is left to the
        template, unless the existing file declares it explicitly.
        """
        source_fields = {
            source_field.name: source_field
            for source_field in source_structure.get_all_fields()
        }
        fields: dict[str, Any] = {}
        untyped_field_names: list[str] = []
        for projected_field in projection.fields:
            if projected_field.name in fields:
                continue
            if (
                projected_field.name in template_field_names
                and projected_field.name not in existing_fields
                and _is_plain_passthrough(projected_field)
            ):
                continue

            generated_field = _build_generated_field(
                projected_field=projected_field,
                source_field=(
                    source_fields[projected_field.source_field_name]
                    if projected_field.source_field_name is not None
                    else None
                ),
            )
            existing_field = existing_fields.get(projected_field.name)
            merged_field = _merge_field(
                existing_field=(
                    existing_field if isinstance(existing_field, dict) else {}
                ),
                generated_field=generated_field,
            )
            if not merged_field.get("data_type"):
                untyped_field_names.append(projected_field.name)
            fields[projected_field.name] = merged_field

        if untyped_field_names:
            raise StructureGenerationException(
                f"Cannot type field(s) {untyped_field_names} of '{structure_id}': "
                f"they are computed by an expression. Wrap the expression in a "
                f"CAST, set data_type in target_from_sources_mapping, or set "
                f"data_type on the field in the structure file"
            )
        return fields

    def _seed_structure_characterisations(
        self,
        projection: StructureProjection,
        source_structure: Structure,
        structure_name: str,
    ) -> list[dict[str, Any]]:
        """Carry over the source keys whose fields are all selected.

        Linked fields are renamed like the projection renames them, and the
        source structure name inside a characterisation name is replaced by
        the target one (pk_refined_x becomes pk_v_refined_x).
        """
        target_by_source_name: dict[str, str] = {}
        for projected_field in projection.fields:
            if (
                projected_field.source_field_name is not None
                and projected_field.expression is None
                and projected_field.source_field_name not in target_by_source_name
            ):
                target_by_source_name[projected_field.source_field_name] = (
                    projected_field.name
                )

        characterisations: list[dict[str, Any]] = []
        for characterisation in source_structure.characterisations:
            linked_fields = characterisation.linked_fields or []
            if not all(
                linked_field in target_by_source_name for linked_field in linked_fields
            ):
                continue
            characterisation_content = characterisation.to_dict()
            characterisation_content["name"] = characterisation.name.replace(
                source_structure.name,
                structure_name,
            )
            if linked_fields:
                characterisation_content["linked_fields"] = [
                    target_by_source_name[linked_field]
                    for linked_field in linked_fields
                ]
            characterisations.append(characterisation_content)
        return characterisations

    def _check_characterisation_links(
        self,
        content: dict[str, Any],
        available_field_names: set[str],
        structure_id: str,
        warnings: list[str],
    ) -> None:
        """Warn about structure characterisations linked to missing fields."""
        for characterisation in content.get("characterisations") or []:
            if not isinstance(characterisation, dict):
                continue
            missing_fields = [
                linked_field
                for linked_field in characterisation.get("linked_fields") or []
                if linked_field not in available_field_names
            ]
            if missing_fields:
                warnings.append(
                    f"Characterisation '{characterisation.get('name')}' of "
                    f"'{structure_id}' links missing field(s) {missing_fields}"
                )

    def _summarize_changes(
        self,
        existing_content: dict[str, Any] | None,
        generated_content: dict[str, Any],
    ) -> list[str]:
        """Describe the differences between the file and the generated content."""
        if existing_content is None:
            return [f"new structure with {len(generated_content['fields'])} field(s)"]

        existing_fields: dict[str, Any] = existing_content.get("fields") or {}
        generated_fields: dict[str, Any] = generated_content["fields"]
        added_fields = [
            field_name
            for field_name in generated_fields
            if field_name not in existing_fields
        ]
        updated_fields = [
            field_name
            for field_name in generated_fields
            if field_name in existing_fields
            and (existing_fields[field_name] or {}) != generated_fields[field_name]
        ]
        removed_fields = [
            field_name
            for field_name in existing_fields
            if field_name not in generated_fields
        ]

        changes: list[str] = []
        for label, field_names in (
            ("added", added_fields),
            ("updated", updated_fields),
            ("removed", removed_fields),
        ):
            if field_names:
                changes.append(
                    f"{label} {len(field_names)} field(s): {', '.join(field_names)}"
                )
        if not changes and list(existing_fields) != list(generated_fields):
            changes.append("reordered fields")

        for key, value in generated_content.items():
            if key != "fields" and existing_content.get(key) != value:
                changes.append(f"updated '{key}'")
        return changes


def split_entity_id(entity_id: str) -> tuple[str, str]:
    """Split <namespace>.<name> into its namespace and name."""
    if "." not in entity_id:
        return NldNamespace.ROOT_VALUE, entity_id
    namespace, name = entity_id.rsplit(
        ".",
        maxsplit=1,
    )
    return namespace, name


def _is_plain_passthrough(projected_field: ProjectedField) -> bool:
    """Whether the field is a source field selected unchanged."""
    return (
        projected_field.source_field_name == projected_field.name
        and projected_field.expression is None
        and projected_field.data_type is None
    )


def _get_template_name(template: Any) -> str:
    """Return the name of a template entry, written as a name or a mapping."""
    if isinstance(template, dict):
        return str(template.get("name"))
    return str(template)


def _build_generated_field(
    projected_field: ProjectedField,
    source_field: Field | None,
) -> dict[str, Any]:
    """Build the generated content of one field from its source field."""
    field_content: dict[str, Any] = {}
    if source_field is not None:
        field_content = source_field.to_dict()
        field_content.pop(
            "name",
            None,
        )
        field_content.pop(
            "field_template",
            None,
        )
        if source_field.data_type:
            field_content["data_type"] = FieldDataType(
                data_type=source_field.data_type,
                length=source_field.length,
                precision=source_field.precision,
            ).to_compact_string()
        field_content.pop(
            "length",
            None,
        )
        field_content.pop(
            "precision",
            None,
        )
        if "characterisations" in field_content:
            field_content["characterisations"] = [
                _compact_field_characterisation(characterisation)
                for characterisation in field_content["characterisations"]
            ]
    if projected_field.data_type is not None:
        field_content["data_type"] = projected_field.data_type
    return field_content


def _compact_field_characterisation(characterisation: dict[str, Any]) -> Any:
    """Write a characterisation without attributes in its short string form."""
    if (
        characterisation.get("name") == characterisation.get("characterisation")
        and not characterisation.get("attributes")
        and set(characterisation) <= {"name", "characterisation", "attributes"}
    ):
        return characterisation["characterisation"]
    return characterisation


def _merge_field(
    existing_field: dict[str, Any],
    generated_field: dict[str, Any],
) -> dict[str, Any]:
    """Merge one generated field into its existing definition.

    Generator-owned keys come from the generated field, except a data type
    the generator could not infer, which is kept from the existing field.
    Every other key keeps its existing value.

    Existing keys keep their order, so a regeneration never reorders a
    hand-written field. A key the existing field lacks is inserted before
    the first existing key that follows it in the Field model order.

    Example:
        Merging a generated ``description`` into an existing
        ``{data_type, characterisations}`` field gives
        ``{description, data_type, characterisations}``.
    """
    merged_field: dict[str, Any] = {}
    for key, value in existing_field.items():
        if key not in GENERATOR_OWNED_FIELD_KEYS:
            merged_field[key] = value
        elif key in generated_field:
            merged_field[key] = generated_field[key]
        elif key == "data_type":
            merged_field[key] = value

    key_ranks = {key: rank for rank, key in enumerate(Field.model_fields)}
    ordered_keys = list(merged_field)
    added_keys = sorted(
        (key for key in generated_field if key not in merged_field),
        key=lambda key: key_ranks.get(key, len(key_ranks)),
    )
    for added_key in added_keys:
        added_rank = key_ranks.get(added_key, len(key_ranks))
        insert_index = next(
            (
                index
                for index, ordered_key in enumerate(ordered_keys)
                if key_ranks.get(ordered_key, len(key_ranks)) > added_rank
            ),
            len(ordered_keys),
        )
        ordered_keys.insert(
            insert_index,
            added_key,
        )

    return {
        key: merged_field[key] if key in merged_field else generated_field[key]
        for key in ordered_keys
    }
