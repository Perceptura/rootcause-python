# rootcause-sdk

[RootCause](https://rootcause.ai) is a causal AI platform: bring your data, discover causal structure, train digital twins, and ask what-if questions. This is the official Python SDK. Full docs: [docs.rootcause.ai](https://docs.rootcause.ai).

## Installation

```bash
pip install rootcause-sdk
```

## Quick start

```python
import rootcause as rc
import pandas as pd

rc.login()                                   # ROOTCAUSE_API_KEY, or browser login

df = pd.read_csv("lalonde.csv")

graph = rc.discover(df, target="re78")       # causal discovery on a DataFrame
graph.pin("treat", "re78")                   # domain knowledge
twin = graph.train()

ate = twin.intervene({"treat": rc.set(1)}, where={"re75": ("<", 5000)})
ate.summary
```

Nothing above mentions a workspace: direct mode keeps platform ceremony out of sight and reuses uploads by content hash.

## Platform mode

The same classes work against everything your team builds in the RootCause UI:

```python
ws = rc.workspace("Calix Forecasting")

ws.sources["shipments"].to_frame()           # tab-completes live names
ws.upload(df, name="shipments-v2")

twin = ws.twin("C8 Temporal")                # trained by a colleague — just there
fc = twin.forecast(horizon=24)
fc.to_frame()                                # tidy long format, straight to pandas

twin.ask("what happens to bookings if we cut trade shows entirely?")
```

## The power-user primitive

Every simulation family is a wrapper over conditional sampling. The SDK exposes it raw:

```python
draws = twin.sample(n=10_000, do={"price": rc.pct(+10)}, where={"region": "FL"}, seed=42)
draws.to_frame()                             # one row per joint posterior draw
```

Interventions: `rc.set(value)`, `rc.pct(+15)`, `rc.add(-5)`, `rc.prob("yes", 0.8)`, `rc.adjust_prob("yes", +10)`, `rc.members(include=[...], size=4)`. Bare values mean `rc.set`. Conditions: `{"region": "EMEA"}` or `{"re75": ("<", 5000)}`.

## Ontology queries

```python
onto = ws.ontology
onto.concepts

result = onto.query(
    select=["customer", "revenue"],
    where=[("region", "==", "US")],
    group_by=["customer"],
    order_by="-revenue",
    aggregate={"revenue": "sum"},
)
result.to_frame()

onto.ask("average revenue per customer in Florida last quarter")
```

## Portable twins

```python
twin.save("c8.rctwin")                       # export zip with trained model params
twin2 = rc.load_twin("c8.rctwin")            # later, anywhere, same auth
```

## Authentication

`rc.login()` resolves credentials in order: explicit `api_key="pk_…"` → `ROOTCAUSE_API_KEY` / `ROOTCAUSE_BASE_URL` env vars → cached OAuth token in `~/.rootcause/` → interactive browser login (PKCE; remote kernels get a paste-the-code fallback). Create API keys under **Organisation → API** on your platform.

## License

MIT
