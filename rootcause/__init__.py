"""RootCause SDK: causal discovery, digital twins, and ontology queries from Python.

Two modes, one object model:

    import rootcause as rc
    rc.login()

    ws = rc.workspace("Calix Forecasting")            # platform mode
    twin = ws.twin("C8 Temporal")
    twin.forecast(horizon=24).to_frame()

    graph = rc.discover(df, target="re78")            # direct mode — no workspace ceremony
    twin = graph.train()
    twin.intervene({"treat": rc.set(1)}, where={"re75": ("<", 5000)})
"""

from typing import TYPE_CHECKING, Any

from rootcause import direct as _direct
from rootcause._http import Transport, resolve_transport
from rootcause.errors import (
    AuthenticationError,
    JobFailedError,
    JobTimeoutError,
    KindMismatchError,
    NotFoundInWorkspaceError,
    RootCauseApiError,
    RootCauseError,
)
from rootcause.graph import Graph
from rootcause.interventions import add, adjust_prob, mean_metrics, members, metric, pct, prob, set  # noqa: A004
from rootcause.ontology import Ontology, OntologyQueryResult
from rootcause.results import ForecastResult, SampleDraws, SimulationResult
from rootcause.twin import Twin
from rootcause.workspace import Connector, DataView, Source, Workspace

if TYPE_CHECKING:
    import pandas as pd
    from pathlib import Path

__version__ = "0.2.0"

_session: dict[str, Transport | None] = {"transport": None}


def login(api_key: str | None = None, base_url: str | None = None) -> None:
    """Authenticate the module-level session.

    Resolution order: explicit api_key → ROOTCAUSE_API_KEY (with
    ROOTCAUSE_BASE_URL) → cached OAuth token in ~/.rootcause → interactive
    browser login (PKCE; prints a URL to paste a code from on remote kernels).
    """
    if _session["transport"] is not None:
        _session["transport"].close()
    _session["transport"] = resolve_transport(api_key=api_key, base_url=base_url)


def _transport() -> Transport:
    if _session["transport"] is None:
        login()
    transport = _session["transport"]
    assert transport is not None
    return transport


def workspaces() -> "pd.DataFrame":
    """All workspaces the session can see."""
    import pandas as pd

    envelope = _transport().request("GET", "/api/v1/workspaces")
    rows = [
        {"id": doc.get("id") or doc.get("_id"), "name": doc.get("name")}
        for doc in envelope.get("data", [])
        if doc.get("name") != _direct.SCRATCH_WORKSPACE_NAME
    ]
    return pd.DataFrame(rows, columns=["id", "name"])


def workspace(needle: str, *, create: bool = False) -> Workspace:
    """Resolve a workspace by name or id; create=True creates it when missing."""
    transport = _transport()
    envelope = transport.request("GET", "/api/v1/workspaces")
    docs = list(envelope.get("data", []))
    for doc in docs:
        if needle in (doc.get("id"), doc.get("_id"), doc.get("name")):
            return Workspace(transport, doc)
    lowered = needle.lower()
    for doc in docs:
        if str(doc.get("name", "")).lower() == lowered:
            return Workspace(transport, doc)
    if create:
        created = transport.request("POST", "/api/v1/workspaces", json_body={"name": needle})
        return Workspace(transport, created.get("data", created))
    import difflib

    names = [str(doc.get("name")) for doc in docs if doc.get("name") and doc.get("name") != _direct.SCRATCH_WORKSPACE_NAME]
    raise NotFoundInWorkspaceError("workspace", needle, difflib.get_close_matches(needle, names, n=5))


def discover(
    frame: "pd.DataFrame",
    target: str | None = None,
    time: str | None = None,
    entity: str | None = None,
    kind: str | None = None,
    name: str | None = None,
    timeout: float = 3600.0,
) -> Graph:
    """Causal discovery on a DataFrame. Compute runs on the platform; nothing user-visible persists."""
    return _direct.discover(
        frame, target=target, time=time, entity=entity, kind=kind, name=name,
        transport=_transport(), timeout=timeout,
    )


def load_twin(path: "str | Path", timeout: float = 3600.0) -> Twin:
    """Load a .rctwin export zip back into a runnable twin."""
    return _direct.load_twin(path, transport=_transport(), timeout=timeout)


def render_widget(widget: dict[str, Any], theme: str = "light") -> str:
    """Render a widget payload to a self-contained HTML fragment via the platform renderer."""
    envelope = _transport().request(
        "POST", "/api/v1/render/widget", json_body={"widget": widget, "theme": theme}
    )
    return str(envelope.get("data", {}).get("html", ""))


__all__ = [
    "AuthenticationError",
    "Connector",
    "DataView",
    "ForecastResult",
    "Graph",
    "JobFailedError",
    "JobTimeoutError",
    "KindMismatchError",
    "NotFoundInWorkspaceError",
    "Ontology",
    "OntologyQueryResult",
    "RootCauseApiError",
    "RootCauseError",
    "SampleDraws",
    "SimulationResult",
    "Source",
    "Twin",
    "Workspace",
    "add",
    "adjust_prob",
    "discover",
    "load_twin",
    "login",
    "mean_metrics",
    "members",
    "metric",
    "pct",
    "prob",
    "render_widget",
    "set",
    "workspace",
    "workspaces",
    "__version__",
]
