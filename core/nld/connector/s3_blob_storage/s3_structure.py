from nld.structure import Structure


class S3Structure(Structure):
    """Structure subclass for entities stored in an S3-compatible backend.

    Exposes typed accessors over the inherited ``properties`` dict so S3
    state and data backends rely on a documented contract instead of
    reading untyped attributes off the surrounding task or data product.
    """

    @property
    def s3_root_prefix(self) -> str:
        """Top-level S3 prefix for this structure (e.g. landing, raw)."""
        return self.get_properties().get("s3_root_prefix", "")

    @property
    def s3_folder_path(self) -> str:
        """Per-structure folder segment under ``s3_root_prefix``.

        Defaults to the structure name when the underlying property is not
        set explicitly on the YAML.
        """
        return self.get_properties().get("s3_folder_path", self.name)

    @property
    def s3_root_path(self) -> str:
        """Composed S3 root path used by S3-backed state and data managers.

        Built as ``<s3_root_prefix>/<s3_folder_path>``. When
        ``s3_root_prefix`` is empty, returns ``s3_folder_path`` on its own
        to avoid a leading slash.
        """
        if not self.s3_root_prefix:
            return self.s3_folder_path
        return f"{self.s3_root_prefix}/{self.s3_folder_path}"

    @property
    def file_format(self) -> str | None:
        """File format declared on the structure, or None when unset."""
        return self.get_properties().get("file_format")
