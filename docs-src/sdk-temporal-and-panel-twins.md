# Python SDK: Temporal and Panel Twins

Time series and multi-environment data get their own twin kinds with their own machinery: lagged dependencies, latent influence detection, one model per environment, forecasts that explain themselves, and interventions scheduled in time. This guide runs a panel end to end; outputs shown are real transcripts.

| Kind | Kwargs | What it models |
| --- | --- | --- |
| `temporal` | `time=` | one time series with lagged causal structure |
| `multi-environment-static` | `entity=` | the same system observed across environments |
| `multi-environment-temporal` | `time=` + `entity=` | a panel: many environments, each a time series |

Everything from [Working with Digital Twins](sdk-working-with-twins.md) applies unchanged; this page covers what these kinds add.

## A panel in long format

One row per store per month. `time=` names the timestamp column, `entity=` the environment column:

```python
>>> panel.head()
        month   store  price  demand  revenue
0  2024-01-01  london  21.70    68.4    152.0
1  2024-02-01  london  21.74    50.2    107.6
2  2024-03-01  london  22.06    44.8    101.2
3  2024-04-01  london  20.16    54.6    109.7
4  2024-05-01  london  20.43    50.8    102.7

>>> graph = rc.discover(panel, time="month", entity="store")
>>> graph.edges
                 cause   effect  strength  fixed
0  Unknown influence 1   demand  1.000000  False
1  Unknown influence 1  revenue  1.000000  False
2               demand  revenue  0.964863  False
3                month    price  0.842668  False
4                month   demand  0.716051  False
5                month  revenue  0.652976  False
6                store  revenue  1.000000  False
```

Three things in this graph do not exist for static twins:

- **A latent influence.** `Unknown influence 1` is a hidden common cause the engine detected in the data but could not name. It is real model structure, not a column; it cannot be intervened on directly.
- **Time as a cause.** The `month` edges carry trend and seasonality into the variables they touch.
- **The environment as a cause.** The `store` edge says the environments genuinely differ, beyond what the other variables explain.

```python
>>> twin = graph.train()
>>> twin
Twin('sdk-twin-071d6d4d7906 (9)', kind=multi-environment-temporal, version=Z9GMDayscq8dp68W0kq9k, state=trained)
```

## One model per environment

Panel twins hold a model per environment. Sampling narrows with `environments=`, the returned frame carries an `environment` column, and a seed derives stable per-environment child seeds, so comparisons are deterministic:

```python
>>> draws = twin.sample(n=500, environments=["london", "berlin"], seed=3)
>>> draws.to_frame().groupby("environment").mean(numeric_only=True).round(1)
             price  demand  revenue
environment
berlin        20.5    53.8    111.9
london        20.2    18.7     39.6
```

The environments really are heterogeneous: Berlin runs at more than double London's demand under the same prices, exactly the per-store scale the `store -> revenue` edge announced.

## Forecasts that explain themselves

`forecast` runs per environment. `environments=` narrows which, `aggregate=` ("sum", "avg", "min", "max") adds a combined series, and `origin_timestamp` (ms epoch) anchors the start, which is how a backtest aligns a forecast against months the twin never saw:

```python
>>> fc = twin.forecast(horizon=6, targets=["revenue"], aggregate="sum")
>>> fc.to_frame()[["environment", "timestamp", "prediction", "lowerBound", "upperBound"]].head(8).round(1)
  environment      timestamp  prediction  lowerBound  upperBound
0      berlin  1788134400000       127.0        79.3       174.7
1      berlin  1790726400000       120.3        72.6       168.0
2      berlin  1793318400000       126.4        78.7       174.1
3      berlin  1795910400000       134.8        87.1       182.5
4      berlin  1798502400000       141.7        94.0       189.4
5      berlin  1801094400000       143.9        96.2       191.6
6      london  1788134400000        33.0       -23.4        89.3
7      london  1790726400000        26.4       -29.9        82.8
```

Every step carries an attribution: how much of the prediction is trend, season, and each causal parent, with lags named:

```python
>>> fc.to_frame().loc[0, "attribution"]
{'trend': 57.008809220589065,
 'seasonal': -14.227390157397737,
 'parents': 5.410396611499529,
 'delta': 63.652936466984,
 'parentBreakdown': {'demand_lag1': 5.410396611499529}}
```

That `demand_lag1` entry is the lagged dependency discovery found: last month's demand carrying into this month's revenue.

## Interventions scheduled in time

Temporal and panel interventions happen at moments, not in the abstract. `rc.at` wraps any intervention value with when it applies and for how long:

```python
>>> result = twin.intervene(
...     {"price": rc.at(rc.pct(-10), persistent=True)},
...     outcomes=["revenue"],
...     environments=["london"],
... )
>>> result
SimulationResult(panel_intervention, run=VSaJ8L4iFkiAb8eam5pUf, status=completed)
```

| Scheduling | Meaning |
| --- | --- |
| `rc.at(spec, persistent=True)` | applies from the first step onwards |
| `rc.at(spec, duration_steps=6)` | applies for six steps, then reverts |
| `rc.at(spec, timestamp=1782864000000)` | starts at a specific moment (ms epoch) |

Without `rc.at`, an intervention on a temporal twin applies as the engine's default one-shot; with it, you express ramps, windows, and permanent policy changes. Everything composes with `where=` conditions and the metric machinery from [Working with Digital Twins](sdk-working-with-twins.md).

## Working with a subset of environments

`twin.env(...)` pins a handle to some of the panel's environments. Its `graph` re-aggregates the causal adjacency over just those environments — edges carry `agreementRate`, the share of the subset's environments in which discovery found the relationship — and every simulation on the handle is scoped automatically:

```python
>>> eu = twin.env("london", "berlin")
>>> adjacency = eu.graph
>>> print(f"{adjacency.attrs['envCount']} of {adjacency.attrs['totalEnvCount']} environments")
2 of 3 environments
>>> adjacency[["source", "target", "strength", "agreementRate"]]
   source   target  strength  agreementRate
0  demand  revenue  0.950329              1
1   month    price  0.846134              1
2   month   demand  0.693129              1
3   month  revenue  0.623993              1
```

Note what's gone next to the full graph above: the `store -> revenue` edge. Within a two-store slice there is less environment-driven variation to explain — the subset's adjacency is genuinely different structure, not a filter on the full graph. `adjacency(agreement_threshold=...)` turns the edge-survival knob (default 0.5), and `combos()` shows the exact environments the handle resolved to.

Simulations on the handle run only in the subset — same verbs, pre-scoped. A price cut in London and Berlin, leaving Paris untouched:

```python
>>> eu.intervene({"price": rc.at(rc.pct(-10), persistent=True)}, outcomes=["revenue"])
SimulationResult(panel_intervention, run=VSaJAnryhPoDccHKQnyjY, status=completed)

>>> eu.forecast(horizon=3, targets=["revenue"]).to_frame()[
...     ["environment", "timestamp", "prediction", "lowerBound", "upperBound"]
... ].round(1)
  environment      timestamp  prediction  lowerBound  upperBound
0      london  1788134400000        33.0       -23.4        89.3
1      london  1790726400000        26.4       -29.9        82.8
2      london  1793318400000        28.2       -28.1        84.6
3      berlin  1788134400000       127.0        79.3       174.7
4      berlin  1790726400000       120.3        72.6       168.0
5      berlin  1793318400000       126.4        78.7       174.1
```

Over REST this is `POST .../versions/{vId}/graph/slice` — the subset can also be defined by column values or per-environment stat filters, not just exact combos.

## Monthly refresh: assimilate instead of retrain

When next month's rows arrive, the model doesn't need rebuilding. Extend the twin's source with the new rows and fold them into the fitted model with `update()` — seconds, not a training run. It finishes with a status, never an error: `committed` (rows folded in), `up_to_date` (nothing new), or `retrain_required` (the model can't take these rows incrementally — `result.reasons` says why; call `twin.retrain()`).

Static and temporal twins assimilate out of the box; panel twins need the v2 panel engine, an opt-in in the twin builder. London's series as its own temporal twin:

```python
>>> london = panel[panel["store"] == "london"][["month", "price", "demand", "revenue"]]
>>> monthly = rc.discover(london, time="month").train()
>>> monthly.source.extend(new_months)      # two new months of rows
>>> monthly.update()
UpdateResult(status='committed', rows=2)
```

Running `update()` again with nothing new in the source is how a scheduled job stays honest — the second call is a cheap no-op:

```python
>>> monthly.update()
UpdateResult(status='up_to_date', rows=0)
```

The refreshed model forecasts onwards from the assimilated months — note the timestamps start after the two new rows, not before them:

```python
>>> fc = monthly.forecast(horizon=3, targets=["revenue"])
>>> fc.to_frame()[["timestamp", "prediction", "lowerBound", "upperBound"]].round(1)
       timestamp  prediction  lowerBound  upperBound
0  1793404800000        35.9        22.6        49.2
1  1795996800000        36.4        22.7        50.0
2  1798588800000        39.5        25.7        53.4
```

The production shape of this loop is a monthly job: sync or extend the source, call `twin.update()`, branch on the status — `retrain_required` triggers `twin.retrain()` instead of a page at 3am. In Airflow, that's three tasks; pass `webhook_url=` to `update()` if you'd rather be poked than poll, and check `twin.update_eligibility` first when you want the decision without starting a job.

## Run it yourself

The transcript above is the temporal-panel example notebook, end to end:

{% file src="../.gitbook/assets/rootcause-sdk-temporal-panel.ipynb" %}
Download the temporal and panel notebook
{% endfile %}

## Next steps

- [Interactive Apps in Notebooks](sdk-notebook-apps.md): the twin console works on panel twins too
- [Python API Reference](sdk-api-reference.md): full signatures for sample, intervene, forecast
