from nld.flow.sql.transformation.base import SQLRenderingTransformation
from nld.flow.sql.transformation.base_resolver import TransformationResolver
from nld.flow.sql.transformation.deduplicated_select.transformation import (
    DeduplicatedSelectTransformation,
)


class DeduplicatedSelectResolver(TransformationResolver):
    """Resolver for the DEDUPLICATED_SELECT transformation."""

    @property
    def transformation_name(self) -> str:
        return "DEDUPLICATED_SELECT"

    @property
    def builtin_class(self) -> type[SQLRenderingTransformation]:
        return DeduplicatedSelectTransformation

    @property
    def connector_package(self) -> str:
        return "nld.flow.sql.transformation.deduplicated_select.connector"
