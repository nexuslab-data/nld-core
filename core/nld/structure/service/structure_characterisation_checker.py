from typing import TYPE_CHECKING

from nld.structure.field import (
    CharacterisationValidationFinding,
    FieldCharacterisationDefinition,
    resolve_field_characterisation_definitions,
)

if TYPE_CHECKING:
    from nld.service.nld_entity_registry import NldEntityRegistry
    from nld.structure.structure.structure import Structure


class StructureCharacterisationChecker:
    """Checks a structure's field characterisations against a definition catalogue.

    The checker owns the field characterisation definition catalogue (the
    built-in code defaults merged with the project declarations). Build it from
    an entity registry with ``from_registry`` so it resolves and manages the
    catalogue itself, or pass an already-resolved ``catalogue`` directly. The
    structure being checked stays a pure data object: it can call the checker,
    but the checker does not depend on it beyond the ``check`` argument.
    """

    def __init__(
        self,
        catalogue: dict[str, FieldCharacterisationDefinition],
    ) -> None:
        self.catalogue = catalogue

    @classmethod
    def from_registry(
        cls,
        registry: "NldEntityRegistry",
        namespace: str | None = None,
    ) -> "StructureCharacterisationChecker":
        """Build a checker managing the catalogue resolved from the registry."""
        return cls(
            catalogue=resolve_field_characterisation_definitions(
                registry=registry,
                namespace=namespace,
            ),
        )

    def check(
        self,
        structure: "Structure",
    ) -> list[CharacterisationValidationFinding]:
        """Validate every field characterisation of the structure.

        Runs three checks against the managed catalogue and returns one finding
        per problem (empty when every characterisation is valid):

        - the characterisation is a known definition: a field tagged with an
          ``unknown_tag`` that no definition declares is reported;
        - every attribute key is allowed by the definition: an ``enforced``
          attribute on a definition that lists no allowed attributes is
          reported;
        - a definition flagged ``applicable_to_single_field_per_structure``
          appears on at most one field: two fields both tagged
          ``rec_insert_tst`` are reported.

        Returns:
            The list of findings; empty when every characterisation is valid.
        """
        findings: list[CharacterisationValidationFinding] = []
        single_field_usage: dict[str, list[str]] = {}
        for field in structure.get_all_fields():
            for characterisation in field.get_characterisations():
                token = characterisation.characterisation
                definition = self.catalogue.get(token)
                if definition is None:
                    findings.append(
                        CharacterisationValidationFinding(
                            entity=structure.name,
                            field_name=field.name,
                            characterisation=token,
                            message=(
                                f"Unknown field characterisation '{token}'; not "
                                f"a known definition"
                            ),
                        )
                    )
                    continue
                if characterisation.attributes:
                    allowed_attributes = definition.allowed_attributes or []
                    for attribute_name in characterisation.attributes:
                        if attribute_name not in allowed_attributes:
                            findings.append(
                                CharacterisationValidationFinding(
                                    entity=structure.name,
                                    field_name=field.name,
                                    characterisation=token,
                                    message=(
                                        f"Attribute '{attribute_name}' not "
                                        f"allowed for '{token}'"
                                    ),
                                )
                            )
                if definition.applicable_to_single_field_per_structure:
                    single_field_usage.setdefault(token, []).append(field.name)

        for token, field_names in single_field_usage.items():
            if len(field_names) > 1:
                findings.append(
                    CharacterisationValidationFinding(
                        entity=structure.name,
                        field_name=", ".join(field_names),
                        characterisation=token,
                        message=(
                            f"'{token}' set on {len(field_names)} fields, "
                            f"expected at most 1"
                        ),
                    )
                )
        return findings
