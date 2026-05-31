from enum import Enum


class StructureModelCardinality(str, Enum):
    """Cardinality of a relationship between two structures."""

    MANY_TO_MANY = "many_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_ZERO = "many_to_zero"
    ONE_TO_MANY = "one_to_many"
    ONE_TO_ONE = "one_to_one"
    ONE_TO_ZERO = "one_to_zero"
    ZERO_TO_MANY = "zero_to_many"
    ZERO_TO_ONE = "zero_to_one"
