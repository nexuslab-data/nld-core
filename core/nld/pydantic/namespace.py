import os


class NldNamespace(str):
    """A validated, normalized namespace string.

    Namespace subclasses str for full backward compatibility: it can be
    used as a dict key, compared with plain strings, split, etc.

    Validation rules applied in __new__:
    - None or empty string are normalized to root (".")
    - Trailing dots are stripped (except the root "." itself)
    - Slashes (/ and \\) are rejected
    - Leading dots (except root ".") are rejected
    - Consecutive dots are rejected

    Examples:
        >>> Namespace("a.b")
        'a.b'
        >>> Namespace(None)
        '.'
        >>> Namespace("a.b.") == Namespace("a.b")
        True
    """

    ROOT_VALUE: str = "."

    def __new__(cls, value: str | None = None) -> "NldNamespace":
        if value is None or value == "":
            return str.__new__(cls, cls.ROOT_VALUE)

        if not isinstance(value, str):
            raise TypeError(
                f"Namespace expects str or None, got {type(value).__name__}"
            )

        if "/" in value or "\\" in value:
            raise ValueError(f"Namespace must not contain slashes: '{value}'")

        normalized = value.rstrip(".")
        if not normalized:
            return str.__new__(cls, cls.ROOT_VALUE)

        if normalized.startswith("."):
            raise ValueError(
                f"Namespace must not start with a dot (except root '.'): '{value}'"
            )

        if ".." in normalized:
            raise ValueError(f"Namespace must not contain consecutive dots: '{value}'")

        return str.__new__(cls, normalized)

    @property
    def is_root(self) -> bool:
        """True when this namespace is the root namespace."""
        return str(self) == self.ROOT_VALUE

    @property
    def depth(self) -> int:
        """Number of levels from root.

        Root has depth 0, "a" has depth 1, "a.b" has depth 2.
        """
        if self.is_root:
            return 0
        return self.count(".") + 1

    @property
    def parent(self) -> "NldNamespace":
        """Return the parent namespace.

        "a.b.c" -> "a.b", "a" -> ".", "." -> ".".
        """
        if self.is_root:
            return NldNamespace(self.ROOT_VALUE)

        parts = self.split(".")
        if len(parts) == 1:
            return NldNamespace(self.ROOT_VALUE)

        return NldNamespace(".".join(parts[:-1]))

    @property
    def hierarchy(self) -> list["NldNamespace"]:
        """Full path from root to this namespace, inclusive.

        "a.b" -> [Namespace("."), Namespace("a"), Namespace("a.b")].
        """
        if self.is_root:
            return [NldNamespace(self.ROOT_VALUE)]

        parts = self.split(".")
        result: list[NldNamespace] = [NldNamespace(self.ROOT_VALUE)]

        for index in range(len(parts)):
            result.append(NldNamespace(".".join(parts[: index + 1])))

        return result

    def contains(self, other: str) -> bool:
        """True when ``other`` is this namespace or a descendant, per segment."""
        other_namespace = NldNamespace(other)
        return (
            self.is_root
            or other_namespace == self
            or other_namespace.startswith(f"{self}.")
        )

    def is_related_to(self, other: str) -> bool:
        """True when one namespace contains the other."""
        return self.contains(other) or NldNamespace(other).contains(self)

    def append(self, child: str) -> "NldNamespace":
        """Append a relative namespace, e.g. "a".append("b.c") -> "a.b.c"."""
        child_namespace = NldNamespace(child)
        if self.is_root:
            return child_namespace
        if child_namespace.is_root:
            return self
        return NldNamespace(f"{self}.{child_namespace}")

    def relative_to(self, ancestor: str) -> "NldNamespace":
        """Return the part of this namespace below ``ancestor``.

        "a.b.c" relative to "a" -> "b.c", and "a" relative to "a" -> ".".

        Raises:
            ValueError: If ``ancestor`` does not contain this namespace.
        """
        ancestor_namespace = NldNamespace(ancestor)
        if not ancestor_namespace.contains(self):
            raise ValueError(
                f"Namespace '{self}' is not contained in namespace "
                f"'{ancestor_namespace}'"
            )
        if ancestor_namespace.is_root:
            return self
        if ancestor_namespace == self:
            return NldNamespace(self.ROOT_VALUE)
        return NldNamespace(self[len(ancestor_namespace) + 1 :])

    def to_path(self, separator: str = os.sep) -> str:
        """Convert namespace to a filesystem-style path.

        "a.b" -> "a/b" (on Unix), root -> "".
        """
        if self.is_root:
            return ""
        return self.replace(".", separator)

    @classmethod
    def from_path(cls, path: str) -> "NldNamespace":
        """Create a Namespace from a filesystem-style path.

        "a/b" -> Namespace("a.b"), "" -> Namespace(".").
        """
        if not path:
            return cls(cls.ROOT_VALUE)

        normalized = path.replace("\\", ".").replace("/", ".")
        return cls(normalized)


def build_entity_key(namespace: str, entity_name: str) -> str:
    """Build the namespace-qualified key of an entity.

    Root-namespace entities key by bare name; everything else by
    ``<namespace>.<name>`` — the one spelling shared by change sets,
    deploy executors and change-file directives.
    """
    if NldNamespace(namespace).is_root:
        return entity_name
    return f"{namespace}.{entity_name}"
