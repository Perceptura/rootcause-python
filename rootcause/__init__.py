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

Conventions throughout: every long-running call blocks with a progress line and
raises `JobFailedError` on failure; everything tabular answers `to_frame()`;
names resolve case-insensitively, with close-match suggestions on a miss.
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
from rootcause.interventions import add, adjust_prob, at, mean_metrics, members, metric, pct, prob, range, set  # noqa: A004
from rootcause.ontology import Ontology, OntologyQueryResult
from rootcause.results import ForecastResult, SampleDraws, ScoreResult, SimulationResult, UpdateResult
from rootcause.twin import Twin
from rootcause.workspace import Connector, DataView, Source, Workspace

if TYPE_CHECKING:
    import pandas as pd
    from pathlib import Path

__version__ = "0.2.0"

_session: dict[str, Transport | None] = {"transport": None}


def login(api_key: str | None = None, base_url: str | None = None) -> None:
    """Authenticate the module-level session.

    Credentials resolve in order:

    1. an explicit `api_key` argument,
    2. `ROOTCAUSE_API_KEY`, paired with `ROOTCAUSE_BASE_URL`,
    3. a cached OAuth token in `~/.rootcause`,
    4. an interactive browser login (PKCE; on a remote kernel it prints a URL
       to paste a code back from).

    Args:
        api_key: An API key (`pk_...`). When omitted, resolution falls through
            `ROOTCAUSE_API_KEY`, the cached OAuth token in `~/.rootcause/`, then
            an interactive browser login with PKCE.
        base_url: Deployment URL, for example `https://sandbox.rootcause.ai`.
            Falls back to `ROOTCAUSE_BASE_URL`, then the production default.
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


def whoami() -> dict[str, "Any"]:
    """What the current credential is: ids, scopes, auth type, rate limit.

    Returns:
        `userId`, `organisationId`, `workspaceId` (the pin, or None for
        org-wide), `scopes`, `authType`, and `rateLimit`. Needs no scopes, so it
        is the cheap way to fail fast before starting a workflow.
    """
    envelope = _transport().request("GET", "/api/v1/me")
    return envelope.get("data", envelope)


def workspaces() -> "pd.DataFrame":
    """All workspaces the session can see.

    Returns:
        A DataFrame of `id` and `name`. The SDK's internal scratch workspace is
        excluded.
    """
    import pandas as pd

    envelope = _transport().request("GET", "/api/v1/workspaces")
    rows = [
        {"id": doc.get("id") or doc.get("_id"), "name": doc.get("name")}
        for doc in envelope.get("data", [])
        if doc.get("name") != _direct.SCRATCH_WORKSPACE_NAME
    ]
    return pd.DataFrame(rows, columns=["id", "name"])


def workspace(needle: str, *, create: bool = False) -> Workspace:
    """Resolve a workspace by name or id; create=True creates it when missing.

    Args:
        needle: Workspace name or id. Case-insensitive.
        create: Create the workspace when it does not exist.

    Returns:
        The matching [`Workspace`](#workspace).

    Raises:
        NotFoundInWorkspaceError: The name did not resolve, and `create` is
            False. Carries the closest names as suggestions.
    """
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
    force: bool = False,
    timeout: float = 3600.0,
) -> Graph:
    """Causal discovery on a DataFrame. Compute runs on the platform; nothing user-visible persists.

    Uploads the frame (deduplicated by content hash), creates a twin directly
    over the uploaded source, runs discovery, and returns its graph. Identical
    data reuses the previously discovered twin instantly.

    Args:
        frame: The data to discover over.
        target: Outcome column of interest; recorded for downstream defaults.
        time: Time column. Setting it makes the twin temporal.
        entity: Entity or environment column. Setting it makes the twin
            multi-environment.
        kind: One of `static`, `temporal`, `multi-environment-static`,
            `multi-environment-temporal`. Inferred from `time` and `entity` when
            omitted, and must agree with them when given.
        name: Twin name on the platform. Derived from the data when omitted.
        force: Ignore the reuse cache and re-run discovery from scratch. The
            recovery path when a model is corrupt or predates an engine fix.
        timeout: Seconds to wait for the discovery job.

    Returns:
        The discovered [`Graph`](#graph).

    Raises:
        KindMismatchError: An explicit `kind` contradicts `time` and `entity`.
        JobFailedError: Discovery ended in a terminal non-success state.
    """
    return _direct.discover(
        frame, target=target, time=time, entity=entity, kind=kind, name=name,
        force=force, transport=_transport(), timeout=timeout,
    )


def load_twin(path: "str | Path", timeout: float = 3600.0) -> Twin:
    """Load a .rctwin export zip back into a runnable twin.

    Args:
        path: Path to a `.rctwin` file written by `Twin.save()`.
        timeout: Seconds to wait for the import job.

    Returns:
        The imported [`Twin`](#twin), trained parameters included.
    """
    return _direct.load_twin(path, transport=_transport(), timeout=timeout)


def render_widget(widget: dict[str, Any], theme: str = "light") -> str:
    """Render a widget payload to a self-contained HTML fragment via the platform renderer.

    Args:
        widget: A widget payload as emitted by the agent and MCP tools.
        theme: `light` or `dark`.

    Returns:
        The HTML string.

    Raises:
        RootCauseApiError: The payload has no session-less rendering. The error
            lists the renderable kinds.
    """
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
    "at",
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
