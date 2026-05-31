import logging
from typing import Any

import numpy as np
import pandas as pd

from nld.connector.base import QueryWrapper
from nld.connector.postgresql.engine.psycopg2.connector import Psycopg2SQLConnector


class PandasPostgreSQLManager:
    """Manages pandas DataFrame operations for PostgreSQL."""

    def __init__(self, connector: Psycopg2SQLConnector) -> None:
        """
        Initialize the manager with a PostgreSQL connector.

        Args:
            connector: PostgreSQL connector instance
        """
        self.connector = connector

    def insert_dataframe(
        self,
        dataframe: pd.DataFrame,
        table_name: str,
        schema_name: str,
        conflict_merge_fields: list[str] | None = None,
    ) -> Any | None:
        """
        Insert a DataFrame into a PostgreSQL table.

        Uses the connector's execute_bulk_insert method for
        bulk insertion with sqlglot-generated INSERT statements.

        Args:
            dataframe: DataFrame to insert
            table_name: Target table name
            schema_name: Target schema name
            conflict_merge_fields: Optional list of fields to use for
                                   conflict resolution (ON CONFLICT clause)

        Returns:
            None

        Raises:
            ValueError: If connection is not available
            Exception: If insertion fails
        """
        if self.connector.connection_wrapper.connection is None:
            raise ValueError("Connection is required to execute query")

        if dataframe.shape[0] == 0:
            self.connector.logger.warn(
                f"Empty DataFrame provided for insert into table {table_name} "
                f"on schema {schema_name}"
            )
            self.connector.logger.warn("No update on database applied")
            return None

        self.connector.logger.info(
            f"Inserting {len(dataframe)} rows into table {table_name} "
            f"on schema {schema_name}"
        )

        values = [
            tuple(row)
            for row in dataframe.replace(np.nan, None).to_records(index=False)
        ]

        self.connector.execute_bulk_insert(
            schema_name=schema_name,
            table_name=table_name,
            column_list=list(dataframe.columns),
            rows=values,
            conflict_merge_fields=conflict_merge_fields,
            page_size=1000,
        )

        return None

    def fetch_table(self, table_name: str, schema_name: str = "public") -> pd.DataFrame:
        """
        Fetch a table from PostgreSQL and return it as a DataFrame.

        Args:
            table_name: Name of the table to fetch
            schema_name: Schema name (defaults to "public")

        Returns:
            DataFrame containing the table data
        """
        select_sql = "SELECT * FROM {{ schema_name }}.{{ table_name }}"
        query_wrapper = QueryWrapper(
            query=select_sql,
            params={"schema_name": schema_name, "table_name": table_name},
        )
        result = self.connector.execute_query(query=query_wrapper)
        df = result.get_output_data_as_df()
        logging.info(f"Fetched {len(df)} rows from table {schema_name}.{table_name}")
        return df
