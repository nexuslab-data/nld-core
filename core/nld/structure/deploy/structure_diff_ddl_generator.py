from abc import ABC, abstractmethod

from nld.pydantic.base_model import NldBaseModel
from nld.structure.deploy.structure_diff import StructureDiff
from nld.structure.structure.structure import Structure
from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder


class DDLStatement(NldBaseModel):
    """A single DDL statement with a human-readable description."""

    sql: str
    description: str


class BaseStructureDiffDDLGenerator(ABC):
    """Abstract base for generating DDL from structure diffs.

    Subclasses implement database-specific SQL generation for
    CREATE TABLE and ALTER TABLE statements.
    """

    @property
    @abstractmethod
    def dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        raise NotImplementedError

    @property
    def _ddl_builder(self) -> BaseSqlglotDDLBuilder:
        """Return a DDL builder for this generator's dialect."""
        return BaseSqlglotDDLBuilder(dialect=self.dialect)

    @abstractmethod
    def generate_create_table(
        self,
        structure: Structure,
        schema_name: str,
    ) -> list[DDLStatement]:
        """Generate CREATE TABLE statements for a new structure."""
        raise NotImplementedError

    @abstractmethod
    def generate_alter_statements(
        self,
        diff: StructureDiff,
        schema_name: str,
    ) -> list[DDLStatement]:
        """Generate ALTER TABLE statements for an existing structure."""
        raise NotImplementedError

    def generate(
        self,
        diff: StructureDiff,
        structure: Structure,
        schema_name: str,
    ) -> list[DDLStatement]:
        """Dispatch to create or alter based on whether the table exists."""
        if diff.is_new_table():
            return self.generate_create_table(
                structure=structure,
                schema_name=schema_name,
            )
        return self.generate_alter_statements(
            diff=diff,
            schema_name=schema_name,
        )
