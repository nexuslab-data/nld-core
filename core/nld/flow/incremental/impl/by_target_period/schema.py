import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from nld.engine.pyarrow import PyArrowPydanticStructureMapper
from nld.pydantic import NldBaseModel

# Parquet schema metadata key carrying the non-row fields of a state
# (calendar, watermark, run outcome) as a JSON document.
ENVELOPE_METADATA_KEY = b"nld_envelope"


def write_period_rows_to_parquet(
    rows: list[NldBaseModel],
    row_class: type[NldBaseModel],
    envelope: dict[str, Any],
    local_path: Path,
) -> None:
    """Write per-period rows as a parquet table carrying the envelope.

    The rows schema is derived from ``row_class`` so it follows the state
    models, and the envelope (e.g. the granularity or the scan watermark)
    travels in the schema metadata so the file round-trips losslessly.
    """
    schema = PyArrowPydanticStructureMapper.get_pyarrow_schema(row_class).with_metadata(
        {ENVELOPE_METADATA_KEY: json.dumps(envelope).encode("utf-8")},
    )
    table = pa.Table.from_pylist(
        [row.model_dump() for row in rows],
        schema=schema,
    )
    pq.write_table(table, local_path)


def read_period_rows_from_parquet(
    local_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read back the rows and the envelope written by the function above."""
    table = pq.read_table(local_path)
    metadata = table.schema.metadata or {}
    envelope = json.loads(metadata.get(ENVELOPE_METADATA_KEY, b"{}").decode("utf-8"))
    return table.to_pylist(), envelope
