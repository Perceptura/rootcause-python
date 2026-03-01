# rootcause-sdk

![RootCause causal discovery](https://rootcause.ai/img/platform/causal-discovery.png)

## About RootCause

[RootCause](https://rootcause.ai) is a causal AI platform: you bring your data, define or discover causal structure, and run what-if analyses and simulations. Build digital twins, explore causal graphs, and query outcomes via the UI or the [Model Context Protocol](https://modelcontextprotocol.io). Full docs: [docs.rootcause.ai](https://docs.rootcause.ai).

This package is the official Python SDK for the RootCause platform API.

## Installation

```bash
pip install rootcause-sdk
```

## Quick Start

```python
import asyncio
from rootcause import RootCause

async def main():
    async with RootCause(api_key="pk_your_api_key", workspace_id="ws_your_workspace") as rc:
        # List datasets
        datasets = await rc.datasets.list()

        # Get a dataset schema
        schema = await rc.datasets.schema("dataset_id")

        # Run a simulation
        sim = await rc.simulations.run({
            "digitalTwinVersionId": "dtv_123",
            "interventions": {"price": 120},
        })

asyncio.run(main())
```

## Features

- **Fully async**: built on httpx for high performance
- **Workspace-scoped**: set a default workspace or pass one per call
- **Job polling**: built-in helpers for long-running operations
- **Auto-pagination**: async generators for paginated endpoints
- **Typed**: full type hints throughout

## Configuration

```python
from rootcause import RootCause, RootCauseConfig

config = RootCauseConfig(
    api_key="pk_...",
    base_url="https://platform.rootcause.ai",  # default
    workspace_id="ws_...",                      # optional default
    timeout=30.0,                               # seconds
)
rc = RootCause(config)
```

## Job Polling

```python
from rootcause import RootCause, poll_job

async with RootCause(api_key="pk_...", workspace_id="ws_...") as rc:
    job = await rc.simulations.run({...})

    result = await poll_job(
        lambda: rc.jobs.get(job["data"]["jobId"]),
        interval_seconds=3.0,
        timeout_seconds=600.0,
        on_progress=lambda j: print(f"{j['status']} {j.get('progress', 0)}%"),
    )
```

## Auto-Pagination

```python
from rootcause import RootCause, paginate

async with RootCause(api_key="pk_...", workspace_id="ws_...") as rc:
    async for dataset in paginate(lambda cursor: rc.datasets.list()):
        print(dataset["name"])
```

## License

MIT
