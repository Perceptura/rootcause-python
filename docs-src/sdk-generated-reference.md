# Python SDK: Generated API Reference

## Module functions

The module-level session and the direct-mode entry points.

### rc.login

```python
rc.login(api_key: str | None = None, base_url: str | None = None) -> None
```

Authenticate the module-level session.

Credentials resolve in order:

1. an explicit `api_key` argument,
2. `ROOTCAUSE_API_KEY`, paired with `ROOTCAUSE_BASE_URL`,
3. a cached OAuth token in `~/.rootcause`,
4. an interactive browser login (PKCE; on a remote kernel it prints a URL
   to paste a code back from).

### rc.whoami

```python
rc.whoami() -> dict[str, Any]
```

What the current credential is: ids, scopes, auth type, rate limit.

### rc.workspaces

```python
rc.workspaces() -> pd.DataFrame
```

All workspaces the session can see.

### rc.discover

```python
rc.discover(
    frame: pd.DataFrame,
    target: str | None = None,
    time: str | None = None,
    entity: str | None = None,
    kind: str | None = None,
    name: str | None = None,
    force: bool = False,
    timeout: float = 3600.0,
) -> Graph
```

Causal discovery on a DataFrame. Compute runs on the platform; nothing user-visible persists.

Identical data reuses the previously discovered twin; force=True re-runs
discovery from scratch (the recovery path for corrupt or outdated models).

### rc.load_twin

```python
rc.load_twin(path: str | Path, timeout: float = 3600.0) -> Twin
```

Load a .rctwin export zip back into a runnable twin.

### rc.render_widget

```python
rc.render_widget(widget: dict[str, Any], theme: str = 'light') -> str
```

Render a widget payload to a self-contained HTML fragment via the platform renderer.

## Workspaces and data

Workspaces and what lives in them: sources, data views, connectors.

### Source

An ingested data source — raw rows as imported.

#### Properties

- **id** (`str`)
- **name** (`str`)
- **schema** (`pd.DataFrame`)

#### Source.to_frame

```python
Source.to_frame() -> pd.DataFrame
```

_Undocumented; the signature above is the contract._

#### Source.extend

```python
Source.extend(frame: pd.DataFrame) -> None
```

Append new rows to this source. Blocks until the rows are ingested.

### DataView

A derived, queryable dataset built from one or more sources.

#### Properties

- **id** (`str`)
- **name** (`str`)
- **schema** (`pd.DataFrame`)

#### DataView.to_frame

```python
DataView.to_frame() -> pd.DataFrame
```

_Undocumented; the signature above is the contract._

#### DataView.records

```python
DataView.records(limit: int = 100, cursor: str | None = None) -> list[dict[str, Any]]
```

_Undocumented; the signature above is the contract._

### Connector

An organisation-level connector to an external system (Snowflake, S3, …).

#### Properties

- **id** (`str`)
- **name** (`str`)

#### Connector.test

```python
Connector.test() -> dict[str, Any]
```

Validate that the stored credentials can reach the external system.

#### Connector.browse

```python
Connector.browse(level: str, context: str = {}) -> Any
```

_Undocumented; the signature above is the contract._

#### Connector.query

```python
Connector.query(query: str, *, limit: int = 100, config: Any = {}) -> pd.DataFrame
```

Run a custom query against the external system and return sample rows.

The authoring loop for custom SQL: nothing is stored, database errors
come back verbatim. Extra kwargs (database=, warehouse=, schema=, …)
join the connector config.

#### Connector.import_table

```python
Connector.import_table(
    table: str,
    *,
    name: str | None = None,
    timeout: float = 3600.0,
    config: Any = {},
) -> Source
```

Import one table into the workspace as a new source.

#### Connector.import_query

```python
Connector.import_query(
    query: str,
    *,
    name: str | None = None,
    timeout: float = 3600.0,
    config: Any = {},
) -> Source
```

Import the result of a custom query into the workspace as a new source.

#### Connector.run_import

```python
Connector.run_import(
    config: dict[str, Any],
    *,
    dataset_name: str | None = None,
    timeout: float = 3600.0,
) -> Source
```

_Undocumented; the signature above is the contract._

### Workspace

A workspace handle: sources, datasets (views), twins, connectors, ontology.

#### Properties

- **id** (`str`)
- **name** (`str`)
- **sources** (`_Collection`)
- **datasets** (`_Collection`)
- **twins** (`_Collection`)
- **connectors** (`_Collection`)

#### Workspace.add_connector

```python
Workspace.add_connector(name: str, type: str, credentials: Any = {}) -> Connector
```

Register a connector to an external system (credentials are stored encrypted).

#### Workspace.dataset

```python
Workspace.dataset(needle: str) -> DataView
```

_Undocumented; the signature above is the contract._

#### Workspace.source

```python
Workspace.source(needle: str) -> Source
```

_Undocumented; the signature above is the contract._

#### Workspace.twin

```python
Workspace.twin(needle: str) -> Twin
```

_Undocumented; the signature above is the contract._

#### Workspace.upload

```python
Workspace.upload(
    frame: pd.DataFrame,
    name: str,
    *,
    wait: bool = True,
    timeout: float = 600.0,
) -> Source
```

Upload a DataFrame as a new source (parquet on the wire, full ingest server-side).

#### Workspace.create_twin

```python
Workspace.create_twin(
    name: str,
    *,
    kind: str = 'static',
    dataset_id: str | None = None,
    source_id: str | None = None,
    time_column: str | None = None,
    environment_columns: list[str] | None = None,
    tags: list[str] | None = None,
) -> Twin
```

_Undocumented; the signature above is the contract._

## Twin

Digital twins: forecast, simulate, intervene, score, update.

### Twin

A digital twin handle bound to one version (the latest unless told otherwise).

#### Properties

- **id** (`str`)
- **name** (`str`)
- **kind** (`str`)
- **is_panel** (`bool`)
- **is_temporal** (`bool`)
- **versions** (`list[dict[str, Any]]`)
- **version** (`dict[str, Any]`)
- **version_id** (`str`)
- **source** (`Any`): The raw source backing this version, or None when it trains off a dataset.
- **graph** (`Graph`)
- **update_eligibility** (`dict[str, Any]`): Whether update() would find new data, and whether it can assimilate incrementally.
- **environments** (`pd.DataFrame`): Panel twins: the environments in the version's data, with sample sizes.

#### Twin.at_version

```python
Twin.at_version(version_id: str) -> Twin
```

_Undocumented; the signature above is the contract._

#### Twin.discover

```python
Twin.discover(*, webhook_url: str | None = None, timeout: float = 3600.0) -> Graph
```

Run causal discovery on this version and return the discovered graph.

#### Twin.train

```python
Twin.train(*, webhook_url: str | None = None, timeout: float = 7200.0) -> Twin
```

Train the model for this version, blocking until done.

An already-trained version is returned as-is: the platform's lifecycle
retrains through a new version, not by re-fitting in place. To rebuild
a model from scratch (after an engine fix, or a corrupt artifact), use
rc.discover(df, force=True) and train the fresh twin it returns.

#### Twin.run_pipeline

```python
Twin.run_pipeline(*, webhook_url: str | None = None, timeout: float = 7200.0) -> Twin
```

Discovery + dependencies + roles + training in one pass.

#### Twin.evaluate

```python
Twin.evaluate() -> dict[str, Any]
```

_Undocumented; the signature above is the contract._

#### Twin.new_version

```python
Twin.new_version(
    *,
    bump: str = 'patch',
    base_version_id: str | None = None,
    dataset_id: str | None = None,
) -> Twin
```

Derive a fresh, untrained version from an existing one — the retrain primitive.

Inherits the base version's configuration and causal graph, resets every
training output, and returns the twin pinned to the new version.

#### Twin.retrain

```python
Twin.retrain(*, bump: str = 'patch', timeout: float = 7200.0) -> Twin
```

Create a new version off the latest and train it — the full retrain in one call.

#### Twin.update

```python
Twin.update(*, webhook_url: str | None = None, timeout: float = 3600.0) -> UpdateResult
```

Fold data added to the backing source since the last train/update into the model.

No retrain: incremental assimilation. The job succeeds with a status
rather than failing — `committed`, `up_to_date`, or `retrain_required`
(the model can't take these rows incrementally; result.reasons says
why — call retrain()). Static and temporal twins assimilate out of the
box; panel twins need the v2 panel engine. Requires a trained version;
extend or sync the source first so there is something new.

#### Twin.env

```python
Twin.env(environments: str | dict[str, str] = ()) -> EnvSubset
```

A handle pinned to a subset of this panel twin's environments.

Pass environment names ("london"), envKeys ("store=london"), or exact
{column: value} combos. Everything on the handle — graph, sample,
intervene, forecast — is scoped to the subset.

#### Twin.score

```python
Twin.score(
    rows: pd.DataFrame | list[dict[str, Any]],
    targets: list[dict[str, Any]],
    *,
    max_changes: int = 3,
    constraints: dict[str, Any] | None = None,
    webhook_url: str | None = None,
    timeout: float = 3600.0,
) -> ScoreResult
```

Score rows against target outcomes: each row gets its smallest flip.

Static trained twins only. rows is a DataFrame or list of dicts whose
keys name twin variables; targets is [{"variable": ..., "value": ...}].
Blocks until the run completes and returns the ScoreResult.

#### Twin.sample

```python
Twin.sample(
    n: int = 1000,
    do: dict[str, Any] | None = None,
    where: Any = None,
    environments: list[str] | None = None,
    seed: int | None = None,
) -> SampleDraws
```

Raw joint posterior draws — the primitive every simulation family wraps.

do= applies interventions before sampling; where= scopes them to a
subpopulation. Panel twins sample each environment independently
(environments= narrows which) and derive stable per-environment child
seeds from seed=.

#### Twin.intervene

```python
Twin.intervene(
    do: dict[str, Any],
    where: Any = None,
    metrics: list[dict[str, Any]] | None = None,
    outcomes: list[str] | None = None,
    environments: list[str] | None = None,
    *,
    timeout: float = 3600.0,
) -> SimulationResult
```

Run an intervention simulation and block for the result.

Interventions measure their effect through metrics: pass metrics=[rc.metric(...)]
for full control, or outcomes=["revenue"] for mean-of-column metrics. For raw
effect distributions without metrics, use twin.sample(do=...).

#### Twin.forecast

```python
Twin.forecast(
    horizon: int,
    targets: list[str] | None = None,
    environments: list[str] | None = None,
    confidence: float = 0.95,
    origin_timestamp: int | None = None,
    aggregate: str | None = None,
    *,
    timeout: float = 3600.0,
) -> ForecastResult
```

Forecast `horizon` steps ahead for the target variables.

Panel twins forecast each environment; environments= narrows which, and
aggregate= ("sum", "avg", "min", "max") adds a combined series across
them. origin_timestamp (ms epoch) anchors the forecast start, which is
how backtests align a forecast against data the twin never saw.

#### Twin.ask

```python
Twin.ask(query: str, *, timeout: float = 3600.0) -> SimulationResult
```

Natural-language question → generated scenario → executed simulation.

#### Twin.console

```python
Twin.console(*, height: int = 560, theme: str = '')
```

The interactive causal-graph console under the cell: the same app Claude renders.

Explore edges, type intervention values, and re-run scenarios; every
control round-trips live through the platform's MCP gateway with this
session's credentials. Needs: pip install "rootcause-sdk[jupyter]".

#### Twin.save

```python
Twin.save(
    path: str | Path,
    *,
    include_runs: bool = False,
    timeout: float = 3600.0,
) -> Path
```

Export this twin (trained params included) as a portable .rctwin zip.

### EnvSubset

A panel twin pinned to a subset of its environments.

Everything on the handle runs scoped to the subset: `graph` re-aggregates
the causal adjacency over just these environments, and sample/intervene/
forecast delegate to the twin with environments= filled in.

#### Properties

- **graph** (`pd.DataFrame`)

#### EnvSubset.combos

```python
EnvSubset.combos() -> list[dict[str, str]]
```

The subset as exact {column: value} combos, resolved against the twin's environments.

The listing carries each environment's values as a list ordered by
environmentColumns; zipping the two recovers the combo.

#### EnvSubset.adjacency

```python
EnvSubset.adjacency(agreement_threshold: float | None = None) -> pd.DataFrame
```

The causal adjacency aggregated over just this subset of environments.

Returns the edges as a DataFrame (source, target, strength, agreementRate, …);
frame.attrs carries envCount, sampleSize, totalEnvCount, and the threshold.

#### EnvSubset.sample

```python
EnvSubset.sample(
    n: int = 1000,
    do: dict[str, Any] | None = None,
    where: Any = None,
    seed: int | None = None,
) -> SampleDraws
```

_Undocumented; the signature above is the contract._

#### EnvSubset.intervene

```python
EnvSubset.intervene(
    do: dict[str, Any],
    where: Any = None,
    metrics: list[dict[str, Any]] | None = None,
    outcomes: list[str] | None = None,
    *,
    timeout: float = 3600.0,
) -> SimulationResult
```

_Undocumented; the signature above is the contract._

#### EnvSubset.forecast

```python
EnvSubset.forecast(
    horizon: int,
    targets: list[str] | None = None,
    confidence: float = 0.95,
    origin_timestamp: int | None = None,
    aggregate: str | None = None,
    *,
    timeout: float = 3600.0,
) -> ForecastResult
```

_Undocumented; the signature above is the contract._

## Graph

Discovered causal graphs, and the domain knowledge pinned onto them.

### Graph

The causal graph of a twin version: edges, adjacency, and domain-knowledge pins.

#### Properties

- **nodes** (`list[str]`)
- **edges** (`pd.DataFrame`)

#### Graph.refresh

```python
Graph.refresh() -> Graph
```

_Undocumented; the signature above is the contract._

#### Graph.adjacency

```python
Graph.adjacency(values: str = 'strength') -> pd.DataFrame
```

Adjacency matrix as a labelled DataFrame; values: strength | sign | bool.

#### Graph.to_numpy

```python
Graph.to_numpy(values: str = 'strength')
```

_Undocumented; the signature above is the contract._

#### Graph.to_networkx

```python
Graph.to_networkx()
```

_Undocumented; the signature above is the contract._

#### Graph.pin

```python
Graph.pin(cause: str, effect: str) -> Graph
```

Fix an edge as present: domain knowledge the next discovery run must honour.

#### Graph.forbid

```python
Graph.forbid(cause: str, effect: str) -> Graph
```

Fix an edge as absent (anti-edge).

#### Graph.train

```python
Graph.train(*, timeout: float = 7200.0) -> Twin
```

_Undocumented; the signature above is the contract._

## Results

The result objects twin operations hand back.

### SampleDraws

Raw joint posterior draws from twin.sample(), columnar on the wire.

#### Properties

- **environments** (`list[str]`)

#### SampleDraws.to_frame

```python
SampleDraws.to_frame() -> pd.DataFrame
```

_Undocumented; the signature above is the contract._

### SimulationResult

A completed simulation run: raw outputs plus best-effort tabular and narrative views.

#### Properties

- **results** (`Any`)
- **summary** (`str`)
- **tables** (`list[str]`)

#### SimulationResult.to_frame

```python
SimulationResult.to_frame(path: str | None = None) -> pd.DataFrame
```

Tabularize the result payload.

Simulation families answer with different shapes; this finds record
lists in the payload. With several candidates, pass path="a.b" to pick
one — the error message lists what is available.

#### SimulationResult.export

```python
SimulationResult.export(fmt: str = 'csv') -> bytes
```

_Undocumented; the signature above is the contract._

#### SimulationResult.sweep

```python
SimulationResult.sweep(metric: str | None = None) -> pd.DataFrame
```

Full dose-response curve of a range intervention, one metric at a time.

With metric=None and several metrics on the run, raises with the list of
available metric names.

### ForecastResult

Forecast run with a tidy long-format frame: environment, series, timestamp, values.

#### ForecastResult.to_frame

```python
ForecastResult.to_frame(path: str | None = None) -> pd.DataFrame
```

_Undocumented; the signature above is the contract._

### UpdateResult

Outcome of an incremental model update (assimilation).

#### Properties

- **retrain_required** (`bool`)

### ScoreResult

Verdicts and per-row counterfactual changes from a batch scoring run.

#### Properties

- **digest** (`dict[str, Any]`): Verdict counts, top drivers, and the first row summaries.

#### ScoreResult.to_frame

```python
ScoreResult.to_frame(max_rows: int | None = None) -> pd.DataFrame
```

Every scored row with its full change list, paged transparently.

## Ontology

Ontology concepts and queries over them.

### OntologyQueryResult

Rows out of the ontology query engine, plus the compiled dataset and any warnings.

#### OntologyQueryResult.to_frame

```python
OntologyQueryResult.to_frame(max_rows: int | None = None) -> pd.DataFrame
```

_Undocumented; the signature above is the contract._

### Ontology

The workspace's semantic layer: concepts, and the query engine over them.

#### Properties

- **concepts** (`pd.DataFrame`)

#### Ontology.query

```python
Ontology.query(
    select: list[str] | None = None,
    where: list[tuple[str, str, Any]] | None = None,
    group_by: list[str] | None = None,
    order_by: str | list[str] | None = None,
    aggregate: dict[str, str] | None = None,
    sources: list[str] | None = None,
    limit: int = 1000,
    wide: bool = True,
    page_size: int = 1000,
) -> OntologyQueryResult
```

Execute a structured ontology query; concepts go by name or id.

where clauses are (concept, operator, value) with operators
eq/neq/gt/gte/lt/lte/between/in/contains or their symbols.

#### Ontology.ask

```python
Ontology.ask(prompt: str, page_size: int = 1000) -> OntologyQueryResult
```

Natural-language question, translated server-side; the structured query is echoed back.

## Interventions

The intervention and metric helpers.

### set

```python
set(value: float | int | str | bool) -> dict[str, Any]
```

Set the variable to an exact value.

### pct

```python
pct(value: float) -> dict[str, Any]
```

Relative percentage change: rc.pct(+15) means +15%.

### add

```python
add(value: float) -> dict[str, Any]
```

Relative absolute change: rc.add(-5) means minus five units.

### prob

```python
prob(
    category: str | int | bool | dict[Any, float],
    probability: float | None = None,
) -> dict[str, Any]
```

Set a category's probability: rc.prob("yes", 0.8) or rc.prob({"yes": 0.8}).

### adjust_prob

```python
adjust_prob(category: str | int | bool, delta: float) -> dict[str, Any]
```

Shift a category's probability by percentage points: rc.adjust_prob("yes", +10).

### members

```python
members(
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    size: int | None = None,
    replace: bool = False,
) -> dict[str, Any]
```

Set-valued column intervention: who is in the set, who is out, how big it is.

### at

```python
at(
    spec: Any,
    timestamp: int | None = None,
    persistent: bool | None = None,
    duration_steps: int | None = None,
) -> dict[str, Any]
```

Schedule an intervention in time, for temporal and panel twins.

Wraps a value spec (or bare value) with when it applies and for how long:
rc.at(rc.pct(-10), persistent=True) applies from the first forecast step
onwards; duration_steps limits it; timestamp (ms epoch) anchors the start.

### range

```python
range(
    from_: float | None = None,
    to: float | None = None,
    *,
    steps: int | None = None,
) -> dict[str, Any]
```

Sweep a numeric variable across a grid instead of pinning it: rc.range(15, 30).

Omit from_/to to sweep the variable's observed p05..p95. A scenario carries
at most one range intervention; read the curves back with result.sweep().

### metric

```python
metric(
    name: str,
    sql: str,
    unit: str = 'count',
    higher_is_better: bool = True,
) -> dict[str, Any]
```

A simulation metric: SQL over the sampled frame, registered as df/data/dataset.

Example: rc.metric("avg_revenue", "SELECT AVG(revenue) AS value FROM df", unit="USD")

### mean_metrics

```python
mean_metrics(outcomes: list[str]) -> list[dict[str, Any]]
```

Mean-of-column metrics for each outcome variable, the common case.

## Notebook apps

Notebook host for the platform's interactive app bundles. Requires the `jupyter` extra.

### McpGateway

Stateless JSON-RPC over HTTP against the platform's MCP endpoint.

#### McpGateway.call

```python
McpGateway.call(method: str, params: Any = None) -> Any
```

_Undocumented; the signature above is the contract._

#### McpGateway.call_tool

```python
McpGateway.call_tool(name: str, arguments: dict[str, Any]) -> Any
```

_Undocumented; the signature above is the contract._

#### McpGateway.app_uri_for

```python
McpGateway.app_uri_for(tool_name: str) -> str
```

_Undocumented; the signature above is the contract._

#### McpGateway.read_bundle

```python
McpGateway.read_bundle(uri: str) -> str
```

_Undocumented; the signature above is the contract._

### app

```python
app(
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    theme: str = '',
    height: int = 480,
    transport: Transport | None = None,
)
```

Run an MCP tool and render its interactive app under the cell.

The tool executes server-side with the session's credentials; its App
bundle renders the result and any controls it carries (re-run scenario,
expand table, approve graph change) round-trip live through the gateway.

## Exceptions

The exception hierarchy every call raises from.

### RootCauseError

Base class for every error this SDK raises.

### AuthenticationError

No usable credentials, or the platform rejected the ones provided.

### RootCauseApiError

The API answered with a problem response.

#### RootCauseApiError.from_response

```python
RootCauseApiError.from_response(cls, body: Any, status: int) -> RootCauseApiError
```

_Undocumented; the signature above is the contract._

### JobFailedError

An asynchronous job finished in a terminal non-success state.

### JobTimeoutError

An asynchronous job did not reach a terminal state within the allotted time.

### NotFoundInWorkspaceError

A name or id did not resolve to exactly one object; carries suggestions.

### KindMismatchError

An explicit twin kind contradicts the panel/temporal kwargs supplied with it.
