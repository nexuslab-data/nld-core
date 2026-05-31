from pydantic import Field as PydanticField
from pydantic import model_validator

from nld.pydantic import NldBaseModel


class FieldLineage(NldBaseModel):
    """Defines how a target field is populated from origin fields.

    Supports three modes:
    - origin only: behaves like a plain string mapping.
    - expression only: raw SQL expression (e.g. CURRENT_TIMESTAMP).
    - origin + expression: the expression wraps the resolved origin
      field as its first argument (e.g. COALESCE(origin_field, 'N/A')).
    """

    expression: str | None = PydanticField(
        default=None,
        description=(
            "SQL function or raw expression. When origin is also set, "
            "the resolved origin field is prepended as the first argument"
        ),
    )
    origin: str | None = PydanticField(
        default=None,
        description=(
            "Origin field reference: predecessor_key.field_name "
            "or just field_name for auto-resolution"
        ),
    )

    @model_validator(mode="after")
    def validate_at_least_one_field_set(self) -> "FieldLineage":
        """Ensure at least one of origin or expression is set."""
        if self.origin is None and self.expression is None:
            raise ValueError(
                "At least one of 'origin' or 'expression' must be set on FieldLineage."
            )
        return self

    def has_origin(self) -> bool:
        """Check if this lineage has an origin field reference."""
        return self.origin is not None

    def has_expression(self) -> bool:
        """Check if this lineage has an expression."""
        return self.expression is not None

    def build_select_expression(
        self,
        resolved_origin_field: str | None,
        target_field: str,
    ) -> str:
        """Build the SQL SELECT expression for this lineage.

        Args:
            resolved_origin_field: the resolved origin field name,
                or None when only expression is set.
            target_field: the target field name for aliasing.

        Returns:
            A SQL expression string like "COALESCE(code, 'N/A') AS customer_name".
        """
        if self.expression is not None and resolved_origin_field is not None:
            sql_expr = self._build_wrapped_expression(resolved_origin_field)
        elif self.expression is not None:
            sql_expr = self.expression
        else:
            assert resolved_origin_field is not None
            sql_expr = resolved_origin_field

        if sql_expr == target_field:
            return sql_expr
        return f"{sql_expr} AS {target_field}"

    def _build_wrapped_expression(
        self,
        resolved_origin_field: str,
    ) -> str:
        """Build expression with origin field as first argument.

        Parses the expression to find the function name and existing
        arguments, then prepends the origin field.
        """
        assert self.expression is not None
        expression = self.expression.strip()

        paren_index = expression.find("(")
        if paren_index == -1:
            return f"{expression}({resolved_origin_field})"

        function_name = expression[:paren_index]
        inner = expression[paren_index + 1 : -1].strip()

        if inner:
            return f"{function_name}({resolved_origin_field}, {inner})"
        return f"{function_name}({resolved_origin_field})"
