# NexusLabData - CORE Library

**YAML- and Python-based data projects for extraction, ingestion, transformation, and consumption — with built-in incremental processing across multiple databases and engines.**

[![PyPI version](https://img.shields.io/pypi/v/nld-core.svg)](https://pypi.org/project/nld-core/)
[![Python versions](https://img.shields.io/pypi/pyversions/nld-core.svg)](https://pypi.org/project/nld-core/)
[![License](https://img.shields.io/pypi/l/nld-core.svg)](./LICENSE.md)

> **Status**: alpha. This repository is a **read-only public mirror** of an actively developed
> internal project. External pull requests are not accepted yet — please
> [open an issue](https://github.com/nexuslab-data/nld-core/issues) for bugs and feature requests.

## What it is

`nld-core` (NexusLabData core) gives you a unified way to manage a data project — whether it targets
a single database or spans multiple databases and engines. You describe your **structures** (typed
schemas) and **flows** (how data is extracted, ingested, transformed, and consumed) in YAML, pick a
**connector**, and the framework runs them consistently everywhere.

It ships with standards that make the experience smoother across every project:

- **Structure templates** and **field templates** — consistent, reusable schema definitions.
- **Standard incremental strategies** — "process only what changed" works the same way everywhere.
- **Execution and incremental standard logging** — monitor what ran and where each delta stopped.

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

## License

Apache-2.0. See [LICENSE.md](./LICENSE.md).
