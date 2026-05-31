from nld.flow.sql.transformation.base import SQLRenderingTransformation
from nld.flow.sql.transformation.base_resolver import TransformationResolver
from nld.flow.sql.transformation.select.transformation import SelectRendering


class SelectResolver(TransformationResolver):
    """Resolver for the SELECT transformation."""

    @property
    def transformation_name(self) -> str:
        return "SELECT"

    @property
    def builtin_class(self) -> type[SQLRenderingTransformation]:
        return SelectRendering

    @property
    def connector_package(self) -> str:
        return "nld.flow.sql.transformation.select.connector"
