# Python SDK: API Reference

The complete public surface of `rootcause-sdk`. Conventions throughout: every long-running call blocks with a progress line and raises `JobFailedError` on failure; everything tabular answers `to_frame()`; names resolve case-insensitively with close-match suggestions on a miss.

## Module functions

### rootcause.login

```python
rc.login(api_key=None, base_url=None)
```

Authenticate the module-level session.

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `api_key` | str, optional | None | An API key (`pk_...`). When omitted, resolution falls through `ROOTCAUSE_API_KEY`, the cached OAuth token in `~/.rootcause/`, then an interactive browser login with PKCE. |
| `base_url` | str, optional | None | Deployment URL, for example `https://sandbox.rootcause.ai`. Falls back to `ROOTCAUSE_BASE_URL`, then the production default. |

### rootcause.whoami

```python
rc.whoami()
```

What the current credential is: `userId`, `organisationId`, `workspaceId` (the pin, or None for org-wide), `scopes`, `authType`, and `rateLimit`. Needs no scopes — use it to fail fast before starting a workflow.

### rootcause.workspaces

```python
rc.workspaces()
```

Every workspace the session can see, as a DataFrame of `id` and `name`. The SDK's internal scratch workspace is excluded.

### rootcause.workspace

```python
rc.workspace(needle, create=False)
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `needle` | str | required | Workspace name or id. Case-insensitive; a miss raises `NotFoundInWorkspaceError` with the closest names. |
| `create` | bool | False | Create the workspace when it does not exist. |

Returns a [`Workspace`](#workspace).

### rootcause.discover

```python
rc.discover(frame, target=None, time=None, entity=None, kind=None,
            name=None, force=False, timeout=3600.0)
```

Causal discovery on a DataFrame. Uploads the frame (deduplicated by content hash), creates a twin directly over the uploaded source, runs discovery, and returns its [`Graph`](#graph). Identical data reuses the previously discovered twin instantly.

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `frame` | DataFrame | required | The data to discover over. |
| `target` | str, optional | None | Outcome column of interest; recorded for downstream defaults. |
| `time` | str, optional | None | Time column. Setting it makes the twin temporal. |
| `entity` | str, optional | None | Entity or environment column. Setting it makes the twin multi-environment. |
| `kind` | str, optional | inferred | One of `static`, `temporal`, `multi-environment-static`, `multi-environment-temporal`. Must agree with `time` and `entity`; a mismatch raises `KindMismatchError`. |
| `name` | str, optional | derived | Twin name on the platform. |
| `force` | bool | False | Ignore the reuse cache and re-run discovery from scratch. The recovery path when a model is corrupt or predates an engine fix. |
| `timeout` | float | 3600 | Seconds to wait for the discovery job. |

### rootcause.load_twin

```python
rc.load_twin(path, timeout=3600.0)
```

Import a `.rctwin` export file and return the runnable [`Twin`](#twin).

### rootcause.render_widget

```python
rc.render_widget(widget, theme="light")
```

Render a widget payload (as emitted by agent and MCP tools) to a self-contained HTML fragment via the platform renderer. Returns the HTML string; raises with the list of renderable kinds when the payload has no session-less rendering.

## Intervention and metric constructors

| Function | Produces |
| --- | --- |
| `rc.set(value)` | set the variable to an exact value (a bare value in `do=` means the same) |
| `rc.pct(value)` | relative percentage change, `rc.pct(+15)` is +15 percent |
| `rc.add(value)` | relative absolute change |
| `rc.prob(category, probability)` | set a category's probability; also accepts `rc.prob({"yes": 0.8})` |
| `rc.adjust_prob(category, delta)` | shift a category's probability by percentage points |
| `rc.members(include, exclude, size, replace)` | set-valued column membership |
| `rc.at(spec, timestamp, persistent, duration_steps)` | schedule an intervention in time (temporal and panel twins) |
| `rc.range(from_, to, steps=None)` | sweep a numeric variable across a grid instead of pinning it; read the curves back with `result.sweep()` |
| `rc.metric(name, sql, unit="count", higher_is_better=True)` | a simulation metric; SQL runs over the sampled frame, registered as `df`, `data`, and `dataset` |
| `rc.mean_metrics(outcomes)` | mean-of-column metrics for each named outcome |

Conditions (`where=` anywhere it appears) accept `{"region": "EMEA"}` for equality or `{"income": ("<", 5000)}` with any of `== != > < >= <=`, plus `in` and `not_in`.

## Workspace

Handle over one workspace. Collections resolve by name or id and feed notebook tab completion from live platform state.

| Member | Description |
| --- | --- |
| `ws.id`, `ws.name` | identity |
| `ws.sources` | ingested sources; `ws.sources["shipments"]` returns a [`Source`](#source) |
| `ws.datasets` | derived views; returns [`DataView`](#dataview) handles |
| `ws.twins` | digital twins; returns [`Twin`](#twin) handles |
| `ws.connectors` | organisation connectors; returns [`Connector`](#connector) handles |
| `ws.ontology` | the workspace [`Ontology`](#ontology) |
| `ws.source(n)`, `ws.dataset(n)`, `ws.twin(n)` | single-item shorthands |
| `ws.upload(frame, name, wait=True, timeout=600.0)` | upload a DataFrame as a new source (parquet on the wire, full ingest server side); blocks until the schema materialises |
| `ws.add_connector(name, type, **credentials)` | register a connector to an external system; credentials are stored encrypted and never returned |
| `ws.create_twin(name, kind="static", dataset_id=None, source_id=None, time_column=None, environment_columns=None, tags=None)` | create a twin over a dataset, or directly over a raw source — pass one of the two ids |

## Source

An ingested data source (a Source in the UI).

| Member | Description |
| --- | --- |
| `source.schema` | schema entries as a DataFrame |
| `source.to_frame()` | full contents via parquet export |
| `source.extend(frame)` | append new rows; blocks until ingested |

## DataView

A derived, queryable view (a Dataset in the UI).

| Member | Description |
| --- | --- |
| `view.schema` | schema entries as a DataFrame |
| `view.to_frame()` | full contents via parquet export |
| `view.records(limit=100, cursor=None)` | one page of rows as dicts; pass the previous page's cursor to continue |

## Connector

| Member | Description |
| --- | --- |
| `connector.test()` | prove the stored credentials reach the external system |
| `connector.browse(level, **context)` | walk the external system's hierarchy |
| `connector.query(sql, limit=100, **config)` | run custom SQL with a row cap and get sample rows back as a DataFrame — nothing stored, database errors verbatim |
| `connector.import_table(table, name=None, **config)` | import one table into the workspace; returns the new [`Source`](#source) |
| `connector.import_query(sql, name=None, **config)` | import the result of a custom query as a new source |
| `connector.run_import(config, dataset_name=None, timeout=3600.0)` | raw connector-specific import payload |

## Ontology

| Member | Description |
| --- | --- |
| `onto.concepts` | concepts as a DataFrame: id, name, type, classification, sources |
| `onto["Revenue"]` | one concept by name or id |
| `onto.query(select, where, group_by, order_by, aggregate, sources, limit=1000, wide=True, page_size=1000)` | structured query; concepts by name or id; returns [`OntologyQueryResult`](#ontologyqueryresult) |
| `onto.ask(prompt, page_size=1000)` | natural-language query, translated server side; the structured query is echoed back on the result |

### OntologyQueryResult

| Member | Description |
| --- | --- |
| `result.to_frame(max_rows=None)` | all rows, paged transparently |
| `result.rows`, `result.row_count` | the first page and the total |
| `result.schema` | column schema |
| `result.warnings` | anything the engine wants you to know about the join |
| `result.dataset` | the compiled dataset definition, persistable via the API |
| `result.query` | for `ask`: the structured query the translator produced |

## Graph

The causal graph of a twin version.

| Member | Description |
| --- | --- |
| `graph.nodes` | node names |
| `graph.edges` | DataFrame: cause, effect, strength, fixed |
| `graph.adjacency(values="strength")` | labelled adjacency matrix; `values` is `strength`, `sign`, or `bool` |
| `graph.to_numpy(values="strength")` | the same as an array |
| `graph.to_networkx()` | a `networkx.DiGraph` (install the `graph` extra) |
| `graph.pin(cause, effect)` | fix an edge as present |
| `graph.forbid(cause, effect)` | fix an edge as absent |
| `graph.train(timeout=7200.0)` | train the underlying twin; returns it |
| `graph.refresh()` | drop the cached payload |

## Twin

| Member | Description |
| --- | --- |
| `twin.kind` | `static`, `temporal`, `multi-environment-static`, or `multi-environment-temporal` |
| `twin.version`, `twin.versions`, `twin.at_version(id)` | version access; a twin binds to its latest version by default |
| `twin.graph` | the [`Graph`](#graph) |
| `twin.discover(timeout=3600.0)` | run causal discovery; returns the graph |
| `twin.train(webhook_url=None, timeout=7200.0)` | train; already trained versions return unchanged with a note pointing at `retrain()` |
| `twin.new_version(bump="patch", base_version_id=None, dataset_id=None)` | derive a fresh untrained version — config and graph inherited, training outputs reset |
| `twin.retrain(bump="patch", timeout=7200.0)` | `new_version()` + `train()` in one call |
| `twin.update(webhook_url=None, timeout=3600.0)` | fold new source data into the trained model incrementally; returns [`UpdateResult`](#updateresult) — never raises on `retrain_required` |
| `twin.update_eligibility` | whether `update()` would find new data, without starting a job |
| `twin.environments` | panel twins: the environments in the data, with sample sizes, as a DataFrame |
| `twin.env(*environments)` | panel twins: an [`EnvSubset`](#envsubset) handle pinned to some environments — names, envKeys, or `{column: value}` combos |
| `twin.source` | the raw source backing this version, or None when it trains off a dataset |
| `twin.score(rows, targets, max_changes=3, constraints=None, webhook_url=None, timeout=3600.0)` | batch counterfactuals: each row's smallest flip to reach the targets; returns [`ScoreResult`](#scoreresult) |
| `twin.run_pipeline(timeout=7200.0)` | discovery, dependencies, roles, and training in one pass |
| `twin.evaluate()` | fit metrics |
| `twin.sample(n=1000, do=None, where=None, environments=None, seed=None)` | raw joint posterior draws; returns [`SampleDraws`](#sampledraws) |
| `twin.intervene(do, where=None, metrics=None, outcomes=None, environments=None, timeout=3600.0)` | run an intervention simulation; needs `outcomes` or `metrics`; returns [`SimulationResult`](#simulationresult) |
| `twin.forecast(horizon, targets=None, environments=None, confidence=0.95, origin_timestamp=None, aggregate=None, timeout=3600.0)` | forecast (temporal and panel twins); aggregate= adds a combined series across environments; returns `ForecastResult` |
| `twin.ask(query, timeout=3600.0)` | natural-language scenario, generated and executed |
| `twin.console(height=560, theme="")` | the interactive causal console under the cell (jupyter extra) |
| `twin.save(path, include_runs=False, timeout=3600.0)` | export as a portable `.rctwin` file with trained parameters |

## EnvSubset

A panel twin pinned to a subset of its environments — from `twin.env("london", "berlin")`. Same simulation verbs, pre-scoped.

| Member | Description |
| --- | --- |
| `sub.graph` | the causal adjacency re-aggregated over just this subset, as a DataFrame — edges carry `strength` and `agreementRate` (the share of the subset's environments the relationship holds in); `frame.attrs` has envCount, sampleSize, totalEnvCount, agreementThreshold |
| `sub.adjacency(agreement_threshold=None)` | same, with the edge-survival threshold as a knob (default 0.5) |
| `sub.combos()` | the subset resolved to exact `{column: value}` combos |
| `sub.sample(...)`, `sub.intervene(...)`, `sub.forecast(...)` | delegate to the twin with `environments=` filled in |

## SampleDraws

| Member | Description |
| --- | --- |
| `draws.to_frame()` | one row per draw; panel twins gain an `environment` column |
| `draws.n` | draws per sampling unit |
| `draws.environments` | environment keys, when panel |

## SimulationResult

| Member | Description |
| --- | --- |
| `result.summary` | the narrative digest |
| `result.to_frame(path=None)` | tabular results; with several candidate tables, `path` picks one and the error message lists what exists |
| `result.tables` | the candidate table paths |
| `result.results` | the raw payload |
| `result.export(fmt="csv")` | the platform's export of the run |
| `result.scenario`, `result.run_id`, `result.run` | what ran and how |

| `result.sweep(metric=None)` | a range intervention's full dose-response curve as a DataFrame, one metric per call; with several metrics and no `metric=`, raises naming them |

`ForecastResult` adds a tidy long-format `to_frame()` with an `environment` column.

## UpdateResult

| Member | Description |
| --- | --- |
| `result.status` | `committed`, `up_to_date`, or `retrain_required` |
| `result.rows_assimilated` | rows folded into the model, when any |
| `result.retrain_required` | True when the model can't take the rows incrementally — call `twin.retrain()` |
| `result.reasons` | why assimilation wasn't possible, when it wasn't |

## ScoreResult

| Member | Description |
| --- | --- |
| `result.digest` | verdict counts, top drivers, and the first row summaries |
| `result.to_frame(max_rows=None)` | every scored row with its full change list, paged transparently |
| `result.run_id` | the underlying simulation run |

## rootcause.jupyter

```python
from rootcause.jupyter import app

app(tool, arguments=None, theme="", height=480)
```

Run an MCP tool and mount its interactive app under the cell. The tool executes server side; the app's controls round-trip live through the platform's MCP gateway. Requires the jupyter extra. See [Interactive Apps in Notebooks](sdk-notebook-apps.md).

## Exceptions

| Exception | Raised when |
| --- | --- |
| `RootCauseError` | base class for everything below |
| `AuthenticationError` | no usable credentials, or the platform rejected them |
| `RootCauseApiError` | the API answered with an error; carries `status`, `title`, `detail` |
| `JobFailedError` | a job or run ended in a terminal non-success state |
| `JobTimeoutError` | a job outlived its `timeout=` |
| `NotFoundInWorkspaceError` | a name did not resolve; carries close-match suggestions |
| `KindMismatchError` | an explicit `kind=` contradicts the panel and temporal keywords |
