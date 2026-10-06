"""Shared constants for the SQLite connector package."""

SQLITE_DIALECT = "sqlite"
# SQLite has a single, always-attached namespace. Every declared schema
# resolves to it so a structure definition written for PostgreSQL deploys
# unchanged on a local SQLite file.
SQLITE_SCHEMA = "main"
