# Python SDK: Working with Digital Twins

This guide covers the full twin lifecycle: inspecting a discovered graph, encoding domain knowledge, training, sampling raw draws, running interventions and forecasts, and moving trained twins between environments. Outputs shown are real transcripts.

## The causal graph

Discovery returns a `Graph`. Its edges are a DataFrame, and the adjacency matrix comes labelled:

```python
>>> graph = rc.discover(df)
>>> graph.edges
             cause   effect  strength  fixed
0            leads  revenue  0.957978  False
1  marketing_spend    leads  0.864212  False
2      seasonality    leads  0.373061  False

>>> graph.adjacency()
                 marketing_spend  seasonality     leads   revenue
marketing_spend              0.0          0.0  0.864212  0.000000
seasonality                  0.0          0.0  0.373061  0.000000
leads                        0.0          0.0  0.000000  0.957978
revenue                      0.0          0.0  0.000000  0.000000
```

`adjacency` also takes `values="sign"` or `values="bool"`, and `to_numpy()` and `to_networkx()` convert onward (networkx needs `pip install "rootcause-sdk[graph]"`).

## Domain knowledge

Encode what you know with two verbs. `pin` fixes an edge as present, `forbid` fixes it as absent, and both write into the version's fixed subgraph that discovery and training honour:

```python
>>> graph.pin("marketing_spend", "leads")
>>> graph.edges
             cause   effect  strength  fixed
0            leads  revenue  0.957978  False
1  marketing_spend    leads  0.864212   True
2      seasonality    leads  0.373061  False
```

## Training

```python
>>> twin = graph.train()
>>> twin
Twin('sdk-twin-ab1ea6651290', kind=static, version=jg8U3O9M6ufF1HJW3XSOO, state=trained)
```

`train` blocks until the model is fitted. Calling it on an already trained version returns the twin unchanged with a note: the platform retrains through new versions, not by re-fitting in place.

Retraining is two verbs. `new_version` derives a fresh, untrained version — configuration and causal graph inherited from the base, every training output reset — and `retrain` is `new_version` plus `train` in one call:

```python
>>> fresh = twin.new_version(bump="minor")   # 1.0.0 -> 1.1.0, untrained
>>> trained = twin.retrain()                 # derive + train, blocks until fitted
```

Version numbers never collide: the bumped component skips past any label already taken. To rebuild a *direct-mode* model from scratch (after an engine fix, or a corrupt artifact), `rc.discover(df, force=True)` remains the recovery path.

In platform mode you rarely train at all; a twin someone trained in the UI is ready to query:

```python
>>> twin = ws.twin("C8 Temporal")
```

## Keeping a trained model current

New rows landing in the twin's backing source do not require a retrain. `update()` folds them into the trained model incrementally — seconds, not minutes — and reports what happened rather than failing:

```python
>>> result = twin.update()
>>> result
UpdateResult(status='committed', rows=60)
```

The three statuses are the contract: `committed` (new rows folded in), `up_to_date` (nothing new since the last update), and `retrain_required` (the model can't take these rows incrementally — `result.reasons` says why; call `twin.retrain()`). Static and temporal twins assimilate out of the box; panel twins need the v2 panel engine (an opt-in in the twin builder). `twin.update_eligibility` answers the same question read-only, so an orchestrator can decide without starting a job. The full monthly-refresh pattern, including the Airflow shape, is in [Temporal and Panel Twins](sdk-temporal-and-panel-twins.md#monthly-refresh-assimilate-instead-of-retrain).

## Batch scoring

Point the trained model at rows and ask what it would take to change each one's outcome. For every row, the counterfactual engine finds the smallest set of changes that reaches the target — a risk register with an action column:

```python
>>> at_risk = pd.DataFrame([
...     {"customer": "cust-104", "tenure": 3,  "monthly_charge": 92, "support_calls": 5},
...     {"customer": "cust-221", "tenure": 41, "monthly_charge": 45, "support_calls": 0},
... ])
>>> result = twin.score(at_risk, targets=[{"variable": "churn", "value": "no"}])
>>> result.digest["verdictCounts"]
{'flips': 1, 'withinTolerance': 0, 'closestOnly': 0, 'alreadyMet': 1}
>>> result.to_frame()[["label", "flip.variable", "flip.toValue", "changeCount"]]
      label    flip.variable  flip.toValue  changeCount
0  cust-104   monthly_charge          61.0            2
1  cust-221             None           NaN            0
```

Static trained twins only; a non-variable column (like `customer` above) becomes the row label. `max_changes=` caps how much each counterfactual may touch, and `constraints=` locks variables the business cannot move.

## Sweeps

Instead of pinning a variable to one value, sweep it across a grid with `rc.range` and read the full dose-response curve back:

```python
>>> result = twin.intervene({"marketing": rc.range(20, 80, steps=8)}, outcomes=["revenue"])
>>> curve = result.sweep()          # one metric on the run, so no metric= needed
>>> curve.attrs["sweptVariable"]
'marketing'
>>> curve[["causeValue", "effectMean"]].tail(3)
   causeValue  effectMean
5   62.857143   93.858985
6   71.428571  128.703131
7   80.000000  129.031563
```

Each point also carries `effectStd` and a `confidenceInterval`.

One `rc.range` per scenario; every other intervention in it is pinned, so the curve reads as the effect of that one dial in a fixed context.

## Raw sampling

Every simulation the platform offers is built on conditional sampling from the fitted model. The SDK exposes that primitive directly, so you can compute your own estimands instead of waiting for a packaged analysis:

```python
>>> draws = twin.sample(n=2000, seed=42)
>>> draws.to_frame().describe().round(1)
       marketing_spend  seasonality   leads  revenue
count           2000.0       2000.0  2000.0   2000.0
mean              48.2         -0.1   142.8    313.1
std               10.9          1.0    36.9     84.3
min               15.3         -3.6    19.4     60.5
25%               41.2         -0.7   118.2    255.2
50%               48.3         -0.1   141.7    313.0
75%               55.4          0.6   166.8    370.7
max               82.6          2.6   253.0    562.5
```

Apply interventions before sampling with `do=`, and compare against baseline:

```python
>>> boosted = twin.sample(n=2000, do={"marketing_spend": rc.pct(+20)}, seed=42)
>>> pd.DataFrame({
...     "baseline": draws.to_frame().mean(),
...     "do(marketing +20%)": boosted.to_frame().mean(),
... }).round(1)
                 baseline  do(marketing +20%)
marketing_spend      48.2                57.9
seasonality          -0.1                -0.1
leads               142.8               164.9
revenue             313.1               358.0
```

The 20 percent push propagates through the chain the graph discovered: marketing lifts leads, leads lift revenue, and seasonality is untouched because nothing points at it.

**Note:** seeds are reproducible across every twin family. Panel twins sample each environment independently and derive stable per-environment child seeds from your seed, so backtest comparisons are deterministic. Pass `environments=["uk", "france"]` to narrow a panel twin; the returned frame gains an `environment` column.

### Intervention values

A bare value means "set to exactly this". The constructors cover the rest:

| Constructor | Meaning |
| --- | --- |
| `rc.set(120)` | set the variable to 120 |
| `rc.pct(+15)` | relative change of +15 percent |
| `rc.add(-5)` | relative change of -5 units |
| `rc.prob("yes", 0.8)` | set a category's probability to 0.8 |
| `rc.adjust_prob("yes", +10)` | shift a category's probability by 10 percentage points |
| `rc.members(include=["Alice"], size=4)` | set-valued column membership |

Conditions scope any intervention to a subpopulation: `where={"region": "EMEA"}` for equality, or `where={"income": ("<", 5000)}` with any of `== != > < >= <=`.

## Interventions with metrics

`intervene` runs the full simulation machinery server side and blocks for the result. Interventions measure their effect through metrics; the simplest form names outcome columns and gets mean-of-column metrics:

```python
>>> result = twin.intervene({"marketing_spend": rc.pct(+25)}, outcomes=["revenue", "leads"])
>>> result
SimulationResult(intervention, run=VSL59DI43QnsTWDcVszak, status=completed)
>>> result.summary       # the narrative digest
>>> result.to_frame()    # tabular results
```

Full control uses SQL metrics over the sampled frame, which is registered under the table names `df`, `data`, and `dataset`:

```python
>>> result = twin.intervene(
...     {"tech_support": rc.prob("yes", 1.0)},
...     metrics=[rc.metric(
...         "churn_rate",
...         "SELECT AVG(CASE WHEN churn = 'Yes' THEN 1.0 ELSE 0.0 END) AS value FROM df",
...         unit="ratio",
...         higher_is_better=False,
...     )],
... )
```

Calling `intervene` with neither `outcomes` nor `metrics` raises immediately with guidance, before any job is submitted:

```python
>>> twin.intervene({"marketing_spend": rc.pct(+5)})
RootCauseError: Interventions need at least one metric. Pass outcomes=['revenue'] for
mean-of-column metrics, metrics=[rc.metric(...)] for custom SQL, or use
twin.sample(do=...) for raw draws.
```

## Forecasts

Temporal and panel-temporal twins forecast. Target variables are inferred from the version's variable roles when unambiguous, or passed explicitly. [Temporal and Panel Twins](sdk-temporal-and-panel-twins.md) covers forecasting in depth, including attribution and backtest anchoring:

```python
>>> fc = twin.forecast(horizon=24, targets=["revenue"], environments=["uk"])
>>> fc.to_frame()        # environment, series, timestamps, confidence bands
```

## Natural language

`ask` uses the same scenario generator as the platform's New Simulation wizard, then runs the generated scenario:

```python
>>> twin.ask("what happens to bookings if we cut trade shows entirely?")
```

## Portable twins

Twin exports carry the trained model parameters, so a `.rctwin` file round-trips to a runnable model:

```python
>>> twin.save("c8.rctwin")
PosixPath('c8.rctwin')
>>> twin2 = rc.load_twin("c8.rctwin")    # later, anywhere, same authentication
```

Compute always stays on the platform; the file makes the model portable between environments, not the algorithms.

## Next steps

- [Temporal and Panel Twins](sdk-temporal-and-panel-twins.md): time series, environments, scheduled interventions, forecast attribution
- [Ontology Queries](sdk-ontology-queries.md)
- [Interactive Apps in Notebooks](sdk-notebook-apps.md)
- [Python API Reference](sdk-api-reference.md)
