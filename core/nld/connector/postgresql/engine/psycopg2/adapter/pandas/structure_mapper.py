from typing import Any

import pandas as pd

from nld.connector.postgresql import PostgreSQLDataTypes


class PostgreSQLPandasMapper:
    """Maps pandas dtypes to PostgreSQL data types."""

    @staticmethod
    def map_dtype_to_backend(dtype: Any) -> str:
        """
        Map pandas dtype to PostgreSQL type.

        Args:
            dtype: Pandas dtype to map

        Returns:
            PostgreSQL data type string

        Example:
            >>> PostgreSQLPandasMapper.map_dtype_to_backend(pd.Int64Dtype())
            'BIGINT'
        """
        if pd.api.types.is_integer_dtype(dtype):
            return PostgreSQLDataTypes.BIGINT
        if pd.api.types.is_float_dtype(dtype):
            return PostgreSQLDataTypes.DOUBLE_PRECISION
        if pd.api.types.is_bool_dtype(dtype):
            return PostgreSQLDataTypes.BOOL
        if pd.api.types.is_datetime64_any_dtype(dtype):
            return PostgreSQLDataTypes.TIMESTAMPTZ
        return PostgreSQLDataTypes.TEXT
