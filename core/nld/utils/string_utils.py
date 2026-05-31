import re


def split_camel_case_string(input_str: str) -> list[str]:
    return re.findall(r"(?:[A-Z]{2,}(?=[A-Z][a-z]|$))|(?:[A-Z][a-z]+)", input_str)


def un_camel(input_str: str) -> str:
    return " ".join(split_camel_case_string(input_str))


def camel_to_snake(name: str) -> str:
    snake_str = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    snake_str = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", snake_str)
    return snake_str.lower()


def camel_to_kebab(name: str) -> str:
    kebab_str = re.sub(r"(.)([A-Z][a-z]+)", r"\1-\2", name)
    kebab_str = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", kebab_str)
    return kebab_str.lower()
