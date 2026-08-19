"""Scaffold the mkdocs page tree into docs/.

The pages are pure boilerplate: one mkdocstrings directive per module plus the
getting-started prose below. Generating them keeps docs/ out of the repo (it is
gitignored) so there is nothing to fall out of sync with mkdocs.yml's nav, which
is the real source of truth for the reference layout.

    python scripts/generate_mkdocs_pages.py

Run before `mkdocs build` or `mkdocs serve`; `mise run docs` does it for you.
"""

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# (relative path, page title, module to document, blurb). Must stay in step with
# mkdocs.yml's nav: --strict fails the build on any page the nav does not list.
REFERENCE_PAGES: list[tuple[str, str, str, str]] = [
    ("reference/index.md", "Top-level API", "rootcause",
     "The module-level surface: session, workspace lookup, direct-mode entry points."),
    ("reference/workspace.md", "Workspace and data", "rootcause.workspace",
     "Workspaces and the data that lives in them: sources, data views, connectors."),
    ("reference/twin.md", "Twin", "rootcause.twin",
     "Digital twins: forecast, simulate, intervene, score, update."),
    ("reference/graph.md", "Graph", "rootcause.graph",
     "Discovered causal graphs, and the domain knowledge you pin onto them."),
    ("reference/results.md", "Results", "rootcause.results",
     "Result objects returned by twin operations."),
    ("reference/ontology.md", "Ontology", "rootcause.ontology",
     "Ontology concepts and queries over them."),
    ("reference/interventions.md", "Interventions", "rootcause.interventions",
     "The intervention and metric helpers (`rc.set`, `rc.add`, `rc.prob`, ...)."),
    ("reference/jupyter.md", "Jupyter", "rootcause.jupyter",
     "Notebook host for the platform's interactive app bundles. Requires the `jupyter` extra."),
    ("reference/errors.md", "Errors", "rootcause.errors",
     "The exception hierarchy every call raises from."),
]

INDEX = '''\
# rootcause-sdk

Official Python SDK for the [RootCause](https://rootcause.ai) causal AI platform:
causal discovery, digital twins, interventions, and ontology queries from Python.

## Install

```bash
pip install rootcause-sdk
```

Optional extras: `graph` (networkx export), `jupyter` (interactive app widgets).

```bash
pip install "rootcause-sdk[graph,jupyter]"
```

## Authentication

```python
import rootcause as rc

rc.login()
```

`login()` resolves credentials in this order:

1. an explicit `api_key=` argument,
2. `ROOTCAUSE_API_KEY` (paired with `ROOTCAUSE_BASE_URL`, which defaults to
   `https://platform.rootcause.ai`),
3. a cached OAuth token in `~/.rootcause`,
4. an interactive browser login (PKCE; on a remote kernel it prints a URL to
   paste a code back from).

Any call will `login()` implicitly on first use, so the explicit call is only
needed when you want to choose the credential yourself.

## Direct mode

No workspace ceremony: hand `discover()` a DataFrame and get a causal graph
back. Uploads are reused by content hash, so re-running the same frame does not
re-upload or re-discover.

```python
import pandas as pd
import rootcause as rc

df = pd.read_csv("lalonde.csv")

graph = rc.discover(df, target="re78")       # causal discovery on a DataFrame
graph.pin("treat", "re78")                   # domain knowledge
twin = graph.train()

ate = twin.intervene({"treat": rc.set(1)}, where={"re75": ("<", 5000)})
ate.summary
```

## Platform mode

The same object model, against workspaces that persist:

```python
ws = rc.workspace("Calix Forecasting")
twin = ws.twin("C8 Temporal")
twin.forecast(horizon=24).to_frame()
```

## Where to go next

The [API reference](reference/index.md) documents the full public surface; the
package is fully typed, so signatures there are authoritative.
'''


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs-dir", type=Path, default=REPO_ROOT / "docs",
        help="Directory to write the page tree into (default: ./docs).",
    )
    args = parser.parse_args()

    write(args.docs_dir / "index.md", INDEX)
    for relative, title, module, blurb in REFERENCE_PAGES:
        write(args.docs_dir / relative, f"# {title}\n\n{blurb}\n\n::: {module}\n")
    print(f"Wrote {len(REFERENCE_PAGES) + 1} pages into {args.docs_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
