# Python SDK: Interactive Apps in Notebooks

Every RootCause MCP tool ships with an interactive app: the consoles that render inline when you use RootCause from Claude, ChatGPT, or Copilot. The SDK mounts those same apps under notebook cells. Nothing is re-implemented per widget; whatever the platform can render in a chat client, your notebook can render too, and every control round-trips live through the platform with your session's credentials.

## Install

```bash
pip install "rootcause-sdk[jupyter]"
```

That is the whole installation. There is no separate extension, no `jupyter labextension install`, no enable step. The widget front end ships inside the package and renders in JupyterLab, Notebook 7, VS Code notebooks, and Colab.

## The twin console

```python
>>> twin = ws.twin("C8 Temporal")
>>> twin.console()
```

The causal-graph console appears under the cell: the DAG, edge strengths, intervention inputs, and a Run scenario button that executes against the platform and updates in place.

<figure><img src="../.gitbook/assets/sdk-twin-console-scenario-jupyterlab.png" alt="JupyterLab with the quickstart notebook open. Under a twin.console() cell, the interactive twin console shows the discovered causal graph (marketing_spend and seasonality into leads into revenue), intervention sliders with marketing_spend pinned to 60, and a results table reading revenue baseline 308.87, scenario 362.38, change +53.50 (+17.3%)"><figcaption>A scenario run inside JupyterLab: marketing_spend pinned to 60, revenue up 17.3 percent, computed live by the platform.</figcaption></figure>

Every control in that screenshot is live. The sliders pin interventions, Run scenario executes the simulation server side through the MCP gateway with your credentials, and the result lands back in the widget without the cell re-running.

Try it yourself with the quickstart notebook, which ends on this exact console:

{% file src="../.gitbook/assets/rootcause-sdk-quickstart.ipynb" %}
Download the quickstart notebook
{% endfile %}

## Any tool's app

`rootcause.jupyter.app` runs an MCP tool and mounts whichever app that tool declares:

```python
from rootcause.jupyter import app

app("get_source_preview", {"workspaceId": ws.id, "sourceId": source.id})
app("check_background_runs", {"workspaceId": ws.id})
app("query_digital_twin", {"workspaceId": ws.id, "query": "raise price 10 percent"})
```

Tools without a dedicated console render through the generic widgets app as cards. The tool executes server side when the cell runs; the app receives the result and takes over from there.

## How it works

The app bundles are self-contained HTML documents that speak a small JSON-RPC protocol with their host. In a chat client, the host is Claude or ChatGPT. In a notebook, the SDK is the host: the bundle runs in a sandboxed iframe, and when it calls a tool (re-running a scenario, expanding a table), the SDK forwards the call to the platform's MCP gateway over HTTPS and returns the result to the iframe. Bundles are fetched from your platform deployment at render time, so they are always the version your server ships.

{% hint style="info" %}
Static notebook exports (nbconvert, GitHub rendering) show a placeholder where an app would mount, since the app needs a live kernel to answer its tool calls.
{% endhint %}
