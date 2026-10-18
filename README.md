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

Each concept has a detailed guide in the [nld-agents](https://github.com/nexuslab-data-agents/nld-agents) marketplace (the `nld-core-usage` plugin).

| Concept | What it is | Guide |
|---|---|---|
| **Flow** | A unit of data movement/transformation, defined in YAML and backed by a `DataFlowTask` (Python) or a SQL definition. Flows declare their connectors, target structure, and predecessors, and the framework orders and runs them. | `nld-core-usage:guide-flows` |
| **Structure** | A typed schema — fields with data types, lengths, and *characterisations* (primary key, unique, business key, …). Structures can be deployed to a database and diffed against the live schema. | `nld-core-usage:guide-structures` |
| **Connector** | A storage abstraction over a **database** (which also brings a query engine), an **object storage**, or a **file storage** — PostgreSQL, Snowflake, BigQuery, DuckDB, SQLite, S3, Azure Blob, or the local file system. The same flow runs against any connector. | `nld-core-usage:guide-connections` |
| **Incremental** | Strategies (`by_key`, `by_source_tst`, `no_increment`) backed by persisted state and watermarks, so each run propagates only the data that changed at the source. | `nld-core-usage:guide-incremental` |
| **Execution monitoring** | Every flow run and its steps are recorded — status (succeeded / warning / failed), start and end time, the requestor, and the load strategy — to a state backend you can query to see what ran and whether it succeeded. | `nld-core-usage:how-to-get-execution-info` |

## Supported connectors

| Connector | Install extra |
|---|---|
| PostgreSQL | `postgres` |
| Snowflake | `snowflake` |
| BigQuery | `bigquery` |
| DuckDB | `duckdb` |
| SQLite | built-in |
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
nld docs build                               # generate the project documentation site
nld docs serve                               # serve it locally, with the live-state API
nld docs deploy                              # produce a self-contained deployable site
nld docs check                               # gate on documentation coverage and broken references
nld docs catalog build                       # one site per project of a platform catalog
nld docs state build                         # publish the live state as a state.json
```

## Project documentation UI

`nld docs` renders the whole project as a local web application: namespaces,
structures and their fields, flows and their sources, lineage, templates,
governance, scheduling and the markdown that documents them — generated from the
project assets alone, with no database connection.

```bash
nld docs serve --port 8765
```

Served that way, the UI adds a live-state layer read from the project's own
backends: what the deployment backend holds per structure and per flow (with
drift against the repository), the latest execution of every flow, the declared
cadence compared with what actually ran, and the age of the data per structure.
Every state panel degrades to "unavailable" when an environment cannot be
reached, so the project view always works.

Documentation is picked up from the filesystem: a `<entity>.md` next to an asset
documents that asset, a `_namespace.md` in an entity folder documents the
namespace, and the project `README.md` documents the project.

Every page cross-links the assets it mentions: a structure page lists the
flows producing and consuming it plus its deployment options and hooks and
renders the latest committed audit; a flow page shows, per environment, the
predecessors the scheduler resolves (automatic lineage plus the declared
adjustments) and the effective retry budget with the declaration that set it;
template and characterisation pages list the structures and fields using them.
The lineage graph can be focused on one node (its ancestors and descendants
stay lit), panned and zoomed, and the search box matches structures, fields,
flows, namespaces, templates, standards and business terms as you type.

Every identifier is displayed as `[namespace] name`. The list pages
(structures, flows, namespaces, every entity type, a namespace's assets, the
coverage report) carry a filter toolbar: a text box matching names and
descriptions and a namespace type-ahead whose options narrow as you type
(typing `wttj` keeps `wttj` and every namespace under it). A structure page
lists the physical table, that is the declared fields plus the fields its
structure templates contribute, each with its origin. The lineage graph can
be filtered on a namespace the same way (direct neighbours stay visible,
outlined), grouped by namespace, or collapsed to one node per namespace
with aggregated links; zoom buttons sit at the bottom right of the graph,
and a structure a flow references without declaring it is drawn dashed red.

A flow page shows the SQL the task will run: the `<flow>.sql` file next to
the definition, highlighted, or the query auto-rendered from
`target_from_sources_mapping` when there is no file (a rendering failure is
reported on the page instead of failing the build).

`nld docs build` writes the same site without serving it, and
`nld docs deploy` adds a launcher so the folder runs on its own
(`python serve.py`). Both also write `snapshot.json`, the versioned,
machine-readable document the site renders. Everything outside its `meta`
block (build time, generator version, environment) is a pure function of
the repository, so two builds of one commit are identical there and a CI
job can diff snapshots between commits. The static export hides the
"Live state" entry, since only `nld docs serve` answers the state API.

`nld docs serve --open` launches the browser; the live state is served from
a short cache (`--state-ttl`, 60 s by default) and the page's "Refresh now"
button bypasses it. Backend failures reach the browser as a short category
only; the full error goes to the server log.

### Publishing the documentation

The same build serves from a laptop, a bucket or an internal host. Where the
page reads its live state is written beside it in `docs.config.json`
(and `docs.config.js`, which is what a site opened from `file://` reads),
so a published site never hard-codes an endpoint:

```bash
# a static site that reads a published state file
nld docs build --base-url https://docs.example.com/nld --state-url ./state.json

# refresh that state from CI, near the warehouse, on a schedule
nld docs state build --target ./site --env prd
```

Preferring a published `state.json` over a live API keeps the site fully
static: no endpoint to expose, no credentials in a browser, no CORS. The
cost is that the state is only as fresh as the job that writes it;
`nld docs serve` remains the live option for local work.

A platform is several nld projects, so `nld docs catalog build` reads an
`nld_project_catalog.yml` and builds one self-contained site per project
under a shared root, plus an index carrying the dependency order the
catalog declares. Each site gains a project switcher, and each remains
readable on its own:

```bash
nld docs catalog build --catalog ops/nld --target ./platform-docs
```

Uploading is deliberately left to the host's own tooling (`aws s3 sync`,
`gsutil rsync`, a Pages action): the build output is a plain folder, and
putting cloud SDKs and their credentials inside nld-core would buy little.
Access control is likewise the host's job — put the site behind the
internal access layer rather than growing auth here.

`nld docs check` lists the undocumented assets and the cross-references
that point at nothing (a flow source or target, a model link side); it
exits non-zero on a broken reference and, with `--min-coverage 0.8`, when
fewer than 80% of the documentable assets are documented.

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
