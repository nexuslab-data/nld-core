"""DuckDB Engine for SQL operations on Parquet files.

Provides a wrapper around DuckDB for standard operations like reading/writing
Parquet files using SQL syntax.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

if TYPE_CHECKING:
    import pandas as pd


class DuckDBEngine:
    """
    DuckDB engine for SQL operations on Parquet files.

    Provides a lazy-loaded in-memory DuckDB connection with standard methods
    for reading and writing Parquet files.

    Supports context manager pattern for automatic cleanup.

    Example usage:
        # Manual management
        engine = DuckDBEngine()
        df = engine.read_parquet_to_dataframe(Path("data.parquet"))
        engine.write_dataframe_to_parquet(df, Path("output.parquet"), "my_table")
        engine.close()

        # Context manager (recommended)
        with DuckDBEngine() as engine:
            df = engine.read_parquet_to_dataframe(Path("data.parquet"))
            engine.write_dataframe_to_parquet(df, Path("output.parquet"), "my_table")
    """

    def __init__(self) -> None:
        """Initialize DuckDB engine with lazy connection."""
        self._connection: duckdb.DuckDBPyConnection | None = None

    def __enter__(self) -> DuckDBEngine:
        """Enter context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit context manager and close connection."""
        self.close()

    @property
    def is_connected(self) -> bool:
        """Check if the DuckDB connection is currently open."""
        return self._connection is not None

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Lazy-loaded DuckDB in-memory connection."""
        if self._connection is None:
            self._connection = duckdb.connect(":memory:")
        return self._connection

    def close(self) -> None:
        """Close the DuckDB connection if it exists."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def execute(self, query: str) -> duckdb.DuckDBPyConnection:
        """
        Execute a SQL query.

        Args:
            query: SQL query string to execute.

        Returns:
            DuckDB connection after query execution.
        """
        return self.connection.execute(query)

    def drop_table(self, table_name: str) -> None:
        """
        Drop a table if it exists.

        Args:
            table_name: Name of the table to drop.
        """
        self.connection.execute(f"DROP TABLE IF EXISTS {table_name}")

    def register_dataframe(self, df: pd.DataFrame, virtual_table_name: str) -> None:
        """
        Register a pandas DataFrame as a virtual table.

        Args:
            df: Pandas DataFrame to register.
            virtual_table_name: Name of the virtual table.
        """
        self.connection.register(virtual_table_name, df)

    def unregister(self, virtual_table_name: str) -> None:
        """
        Unregister a virtual table.

        Args:
            virtual_table_name: Name of the virtual table to unregister.
        """
        self.connection.unregister(virtual_table_name)

    def create_table_from_view(self, table_name: str, virtual_table_name: str) -> None:
        """
        Create a table from a registered view.

        Args:
            table_name: Name for the new table.
            virtual_table_name: Name of the virtual table.
        """
        self.connection.execute(
            f"CREATE TABLE {table_name} AS SELECT * FROM {virtual_table_name}"
        )

    def copy_to_parquet(self, table_name: str, file_path: Path) -> None:
        """
        Copy a table to a Parquet file.

        Args:
            table_name: Name of the table to copy from.
            file_path: Path where the Parquet file will be written.
        """
        self.connection.execute(f"COPY {table_name} TO '{file_path}' (FORMAT PARQUET)")

    def read_parquet(self, file_path: Path) -> list[tuple[Any, ...]]:
        """
        Read a Parquet file and return all rows.

        Args:
            file_path: Path to the Parquet file.

        Returns:
            List of tuples containing row data.
        """
        query = f"SELECT * FROM read_parquet('{file_path}')"
        result: list[tuple[Any, ...]] = self.connection.execute(query).fetchall()
        return result

    def read_parquet_with_columns(
        self, file_path: Path
    ) -> tuple[list[tuple[Any, ...]], list[str]]:
        """
        Read a Parquet file and return rows with column names.

        Args:
            file_path: Path to the Parquet file.

        Returns:
            Tuple of (rows, column_names).
        """
        query = f"SELECT * FROM read_parquet('{file_path}')"
        result = self.connection.execute(query)
        rows = result.fetchall()
        columns = [desc[0] for desc in self.connection.description]
        return rows, columns

    def query_parquet(self, file_path: Path, query_suffix: str = "") -> Any:
        """
        Execute a custom query on a Parquet file.

        Args:
            file_path: Path to the Parquet file.
            query_suffix: Optional SQL suffix (e.g., "WHERE status = 'ACTIVE'").

        Returns:
            Query result (fetchone by default).
        """
        query = f"SELECT * FROM read_parquet('{file_path}') {query_suffix}"
        return self.connection.execute(query).fetchone()

    def count_parquet_rows(self, file_path: Path) -> int:
        """
        Count rows in a Parquet file.

        Args:
            file_path: Path to the Parquet file.

        Returns:
            Number of rows in the file.
        """
        query = f"SELECT COUNT(*) FROM read_parquet('{file_path}')"
        result = self.connection.execute(query).fetchone()
        return result[0] if result else 0

    def write_dataframe_to_parquet(
        self,
        df: pd.DataFrame,
        file_path: Path,
        table_name: str,
    ) -> None:
        """
        Write a pandas DataFrame to a Parquet file using DuckDB.

        This method:
        1. Drops the table if it exists
        2. Registers the DataFrame as a temporary view
        3. Creates a table from the view
        4. Unregisters the temporary view
        5. Copies the table to a Parquet file

        Args:
            df: Pandas DataFrame to write.
            file_path: Path where the Parquet file will be written.
            table_name: Name to use for the intermediate table.
        """
        virtual_table_name = f"{table_name}_temp"
        self.drop_table(table_name)
        self.register_dataframe(df, virtual_table_name)
        self.create_table_from_view(table_name, virtual_table_name)
        self.unregister(virtual_table_name)
        self.copy_to_parquet(table_name, file_path)

    def execute_aggregate_query(
        self, file_path: Path, select_clause: str
    ) -> tuple[Any, ...] | None:
        """
        Execute an aggregate query on a Parquet file.

        Args:
            file_path: Path to the Parquet file.
            select_clause: SQL SELECT clause (e.g., "COUNT(*), SUM(amount)").

        Returns:
            Query result as a tuple, or None if no results.
        """
        query = f"SELECT {select_clause} FROM read_parquet('{file_path}')"
        result: tuple[Any, ...] | None = self.connection.execute(query).fetchone()
        return result

    def execute_filter_query(
        self, file_path: Path, select_columns: str, where_clause: str
    ) -> list[tuple[Any, ...]]:
        """
        Execute a filtered query on a Parquet file.

        Args:
            file_path: Path to the Parquet file.
            select_columns: Columns to select (e.g., "name, status").
            where_clause: WHERE clause without the WHERE keyword.

        Returns:
            List of matching rows.
        """
        query = f"""
            SELECT {select_columns}
            FROM read_parquet('{file_path}')
            WHERE {where_clause}
        """
        result: list[tuple[Any, ...]] = self.connection.execute(query).fetchall()
        return result
