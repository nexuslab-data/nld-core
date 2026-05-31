import abc
import os
from pathlib import Path

from nld.pydantic import NldBaseModel


class BaseConnectionCredential(NldBaseModel, metaclass=abc.ABCMeta):
    name: str | None = None

    @property
    @abc.abstractmethod
    def type(self) -> str:
        raise NotImplementedError(
            "The type method is not implemented for class: " + str(type(self))
        )


class BaseSqlCredential(BaseConnectionCredential, metaclass=abc.ABCMeta):
    @property
    @abc.abstractmethod
    def type(self) -> str:
        raise NotImplementedError(
            "The type method is not implemented for class: " + str(type(self))
        )


def create_secrets_toml_from_credentials(
    credentials: BaseConnectionCredential,
    directory: str | Path,
) -> Path:
    """Create a secrets.toml file from a credential.

    The credential must have a 'name' attribute set (e.g., PostgreSQLCredential).

    Args:
        credentials: A credential with a name attribute to write.
        directory: The directory where secrets.toml will be created.

    Returns:
        Path to the created secrets.toml file.

    Raises:
        ValueError: If the credential does not have a 'name' set.
        TypeError: If the credential contains unsupported field types.
    """
    if credentials.name is None:
        raise ValueError(
            f"Credential of type {credentials.type} does not have a 'name' "
            "set. Please provide a name for the credential."
        )

    secrets_path = Path(directory) / "secrets.toml"

    lines: list[str] = [
        f"[{credentials.name}]",
        f'type = "{credentials.type}"',
    ]

    # Dump all model fields
    for field_name, value in credentials.model_dump().items():
        if value is None:
            continue
        if isinstance(value, str):
            lines.append(f'{field_name} = "{value}"')
        elif isinstance(value, bool):
            lines.append(f"{field_name} = {str(value).lower()}")
        elif isinstance(value, int | float):
            lines.append(f"{field_name} = {value}")
        else:
            raise TypeError(
                f"Unsupported field type for '{field_name}': {type(value).__name__}. "
                "Only str, bool, int, float, and None are supported."
            )

    content = "\n".join(lines)

    os.makedirs(directory, exist_ok=True)
    with open(secrets_path, "w") as f:
        f.write(content)

    return secrets_path
