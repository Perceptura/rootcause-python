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

## Releasing

Publishing to PyPI is driven entirely by git tags. The tag is the version — `pyproject.toml`
is patched in CI at build time, so don't bother bumping it by hand.

1. Push a tag matching `MAJOR.MINOR.PATCH` (pre-releases like `1.2.0rc1` also work):

   ```bash
   git tag 0.2.0 && git push origin 0.2.0
   ```

2. The `build` job builds the sdist + wheel and runs `twine check --strict`.
3. Trigger the `publish` job (manual) to release to PyPI.

### Required CI variable

Set as a **masked** and **protected** project-level variable in GitLab
(Settings → CI/CD → Variables):

| Variable         | Purpose                                             |
| ---------------- | --------------------------------------------------- |
| `PYPI_API_TOKEN` | PyPI API token (`pypi-...`), scoped to this project |

It is passed to twine as the password with username `__token__`; nothing is
hardcoded in the pipeline.

## License

MIT
