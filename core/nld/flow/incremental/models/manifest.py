from pydantic import field_validator

from nld.pydantic import NldBaseModel


class FlowIncrementalTypeManifest(NldBaseModel):
    """Declarative descriptor locating the modules of an incremental type.

    Carries the dotted import paths the factory needs to load an incremental
    type by name, without committing to a hardcoded layout under
    `nld.flow.incremental`. Holds no imported Python types, so it can be
    populated from a project YAML before any of its target modules is loaded.
    """

    name: str
    logic_module: str
    state_manager_module: str
    backend_package: str
    backend_module_template: str = "{backend_type}_with_{engine}"
    fallback_to_base_backend: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("name must be a non-empty string")
        return value

    @field_validator("logic_module", "state_manager_module", "backend_package")
    @classmethod
    def validate_dotted_module_path(cls, value: str) -> str:
        if "." not in value:
            raise ValueError(
                f"'{value}' must be a fully qualified Python module path "
                "(e.g., 'my_package.module')"
            )
        return value

    @field_validator("backend_module_template")
    @classmethod
    def validate_backend_module_template(cls, value: str) -> str:
        for placeholder in ("{backend_type}", "{engine}"):
            if placeholder not in value:
                raise ValueError(
                    f"backend_module_template '{value}' must contain "
                    f"the placeholder '{placeholder}'"
                )
        return value

    def resolve_backend_module_path(
        self,
        backend_type: str,
        engine: str,
    ) -> str:
        """Build the dotted path of the backend module for the given pair."""
        module_name = self.backend_module_template.format(
            backend_type=backend_type,
            engine=engine,
        )
        return f"{self.backend_package}.{module_name}"
