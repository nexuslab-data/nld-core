from fnmatch import fnmatchcase

from nld.pydantic.base_model import NldBaseModel
from nld.pydantic.namespace import NldNamespace

WILDCARD_CHARACTER = "*"


class NamespaceMappingConfig[MAPPING: NldBaseModel](NldBaseModel):
    """Namespace-keyed configuration resolved to the nearest matching entry.

    Keys are namespaces, the root being ``.``, and may contain shell-style
    wildcards such as ``*.bar``. Resolution walks the namespace hierarchy from
    the most specific level down to the root and, at each level, prefers an
    exact key over a wildcard one.

    Matching level by level — rather than trying every exact key before any
    wildcard — is what lets a wildcard beat a broader exact key: with ``.`` and
    ``*.bar`` both configured, ``foo.bar`` resolves to the wildcard at its own
    level while ``foo.baz`` falls through to ``.``.

    Example YAML:
        mappings:
          .:
            some_setting: root_value
          "*.bar":
            some_setting: bar_value
    """

    mappings: dict[str, MAPPING] = {}

    def find_mapping(self, namespace: str) -> MAPPING | None:
        """Return the nearest mapping for a namespace, or None when unmapped."""
        matching_key = self.find_matching_key(namespace=namespace)
        if matching_key is None:
            return None
        return self.mappings[matching_key]

    def find_matching_key(self, namespace: str) -> str | None:
        """Return the declared key a namespace resolves to, or None.

        Reported as declared — a wildcard stays a wildcard — so callers can tell
        the reader *which* declaration decided a value, not just the value.
        """
        matching_keys = self.find_matching_keys(namespace=namespace)
        if not matching_keys:
            return None
        return matching_keys[0]

    def find_matching_keys(self, namespace: str) -> list[str]:
        """Return every declared key a namespace matches, nearest level first.

        The same walk as ``find_matching_key`` without stopping at the first
        hit, so a setting declared on a broader level stays reachable when the
        nearest mapping does not carry it. Callers resolving a whole mapping
        want the first key; callers resolving one optional setting walk until
        they find a mapping that declares it.

        A wildcard matching several levels is reported once, at the nearest
        level it matched.
        """
        matching_keys: list[str] = []
        for level in reversed(NldNamespace(namespace).hierarchy):
            level_key = str(level)
            if level_key in self.mappings and level_key not in matching_keys:
                matching_keys.append(level_key)

            wildcard_key = self._find_wildcard_key(level=level_key)
            if wildcard_key is not None and wildcard_key not in matching_keys:
                matching_keys.append(wildcard_key)

        return matching_keys

    def get_namespaces(self) -> list[str]:
        """Return all configured namespace keys."""
        return list(self.mappings.keys())

    def _find_wildcard_key(self, level: str) -> str | None:
        """Return the most specific wildcard key matching one hierarchy level.

        Ties are broken by the number of literal (non-wildcard) characters, then
        alphabetically, so the winner never depends on declaration order.
        """
        matching_keys: list[str] = []
        for key in self.mappings:
            if WILDCARD_CHARACTER not in key:
                continue
            if fnmatchcase(
                level,
                pat=key,
            ):
                matching_keys.append(key)

        if not matching_keys:
            return None

        matching_keys.sort(
            key=lambda key: (-len(key.replace(WILDCARD_CHARACTER, "")), key),
        )
        return matching_keys[0]
