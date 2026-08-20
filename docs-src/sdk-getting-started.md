# Python SDK

This guide installs the SDK, authenticates a session, and takes a pandas DataFrame to a discovered causal graph. Every code block below is a real transcript: the output shown is what the call returns.

The SDK has two modes over one object model:

* **Direct mode**: `rc.discover(df)` on a DataFrame. No workspace ceremony, nothing to set up in the UI first.
* **Platform mode**: `rc.workspace(...)` over everything your team builds in the RootCause UI. Twins a colleague trained are simply there.

## Installation

```bash
pip install rootcause-sdk
```

For interactive apps under notebook cells, install the jupyter extra. There is no separate extension to install or enable; the widget front end ships inside the package:

```bash
pip install "rootcause-sdk[jupyter]"
```

## Authentication

First, log the session in:

```python
>>> import rootcause as rc
>>> rc.login()
```

`login` resolves credentials in this order:

1. An explicit key: `rc.login(api_key="pk_...", base_url="https://sandbox.rootcause.ai")`
2. The `ROOTCAUSE_API_KEY` and `ROOTCAUSE_BASE_URL` environment variables
3. A cached OAuth token in `~/.rootcause/`
4. An interactive browser login (OAuth with PKCE). On a remote kernel it prints the URL and accepts a pasted code.

Create API keys under **Organisation home, API card, Create API Key**, and give a key only the scopes the integration needs. See [API Access](api-access.md) for the scope table.

## From DataFrame to causal graph

Load data the way you always do:

```python
>>> import pandas as pd
>>> df = pd.read_csv("marketing.csv")
>>> df.head()
   marketing_spend  seasonality  leads  revenue
0            50.01       -0.460  145.1    307.1
1            53.58        0.743  171.7    370.8
2            46.71       -0.082  140.2    262.2
3            39.31        0.081  119.6    287.4
4            44.54       -0.291  144.5    323.0
```

Then discover. The SDK uploads the frame, waits for ingest and ontology processing, runs causal discovery on the platform, and returns the graph:

```python
>>> graph = rc.discover(df)
>>> graph.edges
             cause   effect  strength  fixed
0            leads  revenue  0.957978  False
1  marketing_spend    leads  0.864212  False
2      seasonality    leads  0.373061  False
```

**Note:** re-running `rc.discover(df)` on identical data reuses the finished twin instantly; the data travels by content hash. `rc.discover(df, force=True)` rebuilds from scratch, which is the recovery path when a model is corrupt or predates an engine fix.

Temporal and panel data are keyword arguments, not a different API:

```python
>>> rc.discover(df, time="month")                       # temporal twin
>>> rc.discover(df, time="month", entity="store_id")    # multi-environment panel twin
```

An explicit `kind=` is validated against those keywords and raises on a mismatch rather than silently training the wrong model family:

```python
>>> rc.discover(df, kind="static", time="month")
KindMismatchError: kind="static" contradicts the kwargs (time=set, entity=unset);
with these kwargs the kind would be "temporal"
```

## Platform mode

Resolve a workspace by name, and everything in it answers by name too. Collection lookups tab-complete from live platform state:

```python
>>> ws = rc.workspace("Customer Analytics")
>>> ws.sources["shipments"].to_frame()      # a source your team uploaded
>>> ws.upload(df, name="shipments-v2")      # or push your own

>>> twin = ws.twin("C8 Temporal")           # trained by a colleague in the UI
>>> fc = twin.forecast(horizon=24)
>>> fc.to_frame()                           # tidy long format, straight into pandas
```

Everything tabular answers `to_frame()`. Everything long-running blocks with a progress line and raises a typed error if the job fails, so a notebook cell either completes or tells you why.

## Jumping to the platform

Every handle knows the page it lives on: `.link()` returns the platform URL, clickable in a notebook and linkified by most terminals.

```python
>>> twin.link()
https://platform.rootcause.ai/{org}/space/{workspace}/twins/{twin}?version=1.0.2

>>> result.link()   # a run links to its own detail view, not just the twin
https://platform.rootcause.ai/{org}/space/{workspace}/twins/{twin}?tab=simulate&simulation={run}
```

Workspaces, sources, datasets, twins, the ontology, and simulation/forecast/scoring runs all answer it. The interactive apps' "Open in RootCause" buttons land on the same pages.

## Next steps

* [Working with Digital Twins](sdk-working-with-twins.md): training, raw sampling, interventions, portable twins
* [Temporal and Panel Twins](sdk-temporal-and-panel-twins.md): time series, environments, forecasts with attribution
* [Ontology Queries](sdk-ontology-queries.md): the semantic layer from Python
* [Interactive Apps in Notebooks](sdk-notebook-apps.md): the consoles Claude renders, under your cells
* [Python API Reference](sdk-api-reference.md): every public function and class
* [REST API Reference](../api-and-integrations/rest-api-reference/): the HTTP surface the SDK is built on
