# nld-core

**Typed, YAML-defined data flows with built-in incremental processing across major SQL warehouses — for data engineers who are tired of rewriting the same boilerplate.**

[![PyPI version](https://img.shields.io/pypi/v/nld-core.svg)](https://pypi.org/project/nld-core/)
[![Python versions](https://img.shields.io/pypi/pyversions/nld-core.svg)](https://pypi.org/project/nld-core/)
[![License](https://img.shields.io/pypi/l/nld-core.svg)](./LICENSE.md)

> **Status**: alpha. This repository is a **read-only public mirror** of an actively developed
> internal project. External pull requests are not accepted yet — please
> [open an issue](https://github.com/nexuslab-data/nld-core/issues) for bugs and feature requests.

## What it is

Moving data across PostgreSQL, Snowflake, BigQuery, and DuckDB usually means writing the same
glue over and over: connection handling, schema definitions, incremental "only process what
changed" logic, retry-safe writes, and dependency ordering between flows. The interesting part —
the transformation — drowns in plumbing.

`nld-core` (Nexus Lab Data core) is a Python framework that turns that plumbing into declarative
configuration. You describe your **structures** (typed schemas) and **flows** (how data moves and
transforms) in YAML, pick a **connector**, and the framework handles execution, write strategies,
and **incremental processing** for you — consistently across every supported warehouse.

## Quickstart

```bash
# Install with the connector extra you need (PostgreSQL shown here)
pip install "nld-core[postgres]"
```

Create a project, declare a flow, and run it:

```yaml
# nld_project.yml
name: my_data_project
version: '0.0.1'
```

```yaml
# flows/my_flow.yml
name: my_flow
task: my_project.tasks.MyDataTask
data_connectors:
  source: source_connector
target_structure: source.my_table
```

```python
# my_project/tasks.py
from typing import ClassVar

from nld.flow.incremental.no_increment.logic import NO_INCREMENT_FLOW_INCREMENTAL_LOGIC
from nld.flow.task import DataFlowTask


class MyDataTask(DataFlowTask):
    """Minimal data flow task."""

    _INCREMENTAL_LOGIC: ClassVar = NO_INCREMENT_FLOW_INCREMENTAL_LOGIC
    init_params = ["source_connector"]

    def run_flow(self) -> None:
        # Your transformation logic here.
        ...
```

```bash
# Execute the flow
nld flow execute --name my_flow
```

## Core concepts

| Concept | What it is |
|---|---|
| **Flow** | A unit of data movement/transformation, defined in YAML and backed by a `DataFlowTask` (Python) or a SQL definition. Flows declare their connectors, target structure, and predecessors, and the framework orders and runs them. |
| **Structure** | A typed schema — fields with data types, lengths, and *characterisations* (primary key, unique, functional key, …). Structures can be deployed to a warehouse and diffed against the live schema. |
| **Connector** | The warehouse/storage abstraction (PostgreSQL, Snowflake, BigQuery, DuckDB, S3, Azure Blob, local files). The same flow definition runs against any supported connector. |
| **Incremental** | Built-in "process only what changed" strategies (`by_key`, `by_source_tst`, `no_increment`) with persisted state and watermarks, so reruns and backfills are safe and cheap. |

## Supported connectors

| Connector | Install extra |
|---|---|
| PostgreSQL | `postgres` |
| Snowflake | `snowflake` |
| BigQuery | `bigquery` |
| DuckDB | `duckdb` |
| S3 | `s3_blob_storage` |
| Azure Blob Storage | `azure_blob_storage` |
| Local File System | built-in |

Install several at once:

```bash
pip install "nld-core[postgres,snowflake,bigquery,duckdb]"
```

## CLI

```bash
nld flow execute --name <flow_name>          # run a flow
nld flow info --name <flow_name>             # inspect a flow
nld flow deps --name <flow_name>             # flow dependency graph as JSON
nld flow state execution get-state <flow_name>   # inspect persisted execution state
nld connection list                          # list configured connections
nld connection get-structure --connection-name <name>   # extract schema from a live database
nld structure info --name <name>             # inspect a structure
nld project info                             # project overview
```

## Requirements

- Python >= 3.12

## Build NLD projects with agents

We maintain a **Claude Code marketplace** of skills that help you scaffold and build a complete
NLD data project — data-platform conventions, connectors, flows, and incremental strategies:

- **NLD agents marketplace**: <https://github.com/nexuslab-data-agents/nld-agents>

It bundles the standard skills our team uses for the data platform, so an agent can help you go
from an empty repo to working flows that follow the NLD conventions.

## Where to next

- **Issues / feature requests**: <https://github.com/nexuslab-data/nld-core/issues>
- **Security**: see [SECURITY.md](./SECURITY.md) for the private disclosure channel.

## License

Apache-2.0. See [LICENSE.md](./LICENSE.md).
