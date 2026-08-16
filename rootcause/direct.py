import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rootcause._http import Transport, poll_job
from rootcause.errors import KindMismatchError, RootCauseError
from rootcause.graph import Graph
from rootcause.twin import Twin
from rootcause.workspace import Workspace

if TYPE_CHECKING:
    import pandas as pd

SCRATCH_WORKSPACE_NAME = ".sdk-scratch"

_KIND_RULES: dict[str, tuple[bool, bool]] = {
    "static": (False, False),
    "temporal": (True, False),
    "multi-environment-static": (False, True),
    "multi-environment-temporal": (True, True),
}


def infer_kind(time: str | None, entity: str | None, kind: str | None) -> str:
    """Infer the twin kind from panel kwargs; an explicit kind must agree with them."""
    inferred = {
        (False, False): "static",
        (True, False): "temporal",
        (False, True): "multi-environment-static",
        (True, True): "multi-environment-temporal",
    }[(time is not None, entity is not None)]
    if kind is None:
        return inferred
    if kind not in _KIND_RULES:
        raise KindMismatchError(f'Unknown kind "{kind}". One of: {", ".join(_KIND_RULES)}')
    needs_time, needs_entity = _KIND_RULES[kind]
    if needs_time != (time is not None) or needs_entity != (entity is not None):
        raise KindMismatchError(
            f'kind="{kind}" contradicts the kwargs (time={"set" if time else "unset"}, '
            f'entity={"set" if entity else "unset"}); with these kwargs the kind would be "{inferred}"'
        )
    return kind


def frame_fingerprint(frame: "pd.DataFrame") -> str:
    """Deterministic content hash of a DataFrame: values, column names, dtypes."""
    import pandas as pd

    digest = hashlib.sha256()
    digest.update(",".join(map(str, frame.columns)).encode())
    digest.update(",".join(str(dtype) for dtype in frame.dtypes).encode())
    digest.update(pd.util.hash_pandas_object(frame, index=False).values.tobytes())
    return digest.hexdigest()[:12]


def scratch_workspace(transport: Transport) -> Workspace:
    """The hidden workspace direct-mode artifacts live in. Created once, then reused."""
    envelope = transport.request("GET", "/api/v1/workspaces")
    for doc in envelope.get("data", []):
        if doc.get("name") == SCRATCH_WORKSPACE_NAME:
            return Workspace(transport, doc)
    created = transport.request(
        "POST",
        "/api/v1/workspaces",
        json_body={"name": SCRATCH_WORKSPACE_NAME, "description": "rootcause-sdk direct mode artifacts"},
    )
    return Workspace(transport, created.get("data", created))


def _ensure_source(workspace: Workspace, frame: "pd.DataFrame", fingerprint: str):
    name = f"sdk-{fingerprint}"
    existing = workspace.sources.get(name)
    if existing is not None:
        return existing
    return workspace.upload(frame, name)


def _find_reusable_twin(
    workspace: Workspace,
    fingerprint: str,
    kind: str,
    time: str | None,
    entity: str | None,
) -> Twin | None:
    tag = f"sdk:{fingerprint}"
    candidates = [
        twin for twin in workspace.twins
        if tag in (twin.doc.get("tags") or []) and twin.kind == kind
    ]
    for twin in sorted(candidates, key=lambda t: str(t.doc.get("createdAt", "")), reverse=True):
        try:
            version = twin.version
        except RootCauseError:
            continue
        if time is not None and version.get("selectedTimeColumnName") not in (None, time):
            continue
        env_columns = version.get("environmentColumns") or twin.doc.get("environmentColumns")
        if entity is not None and env_columns not in (None, [entity]):
            continue
        if version.get("causalGraph") or version.get("lifecycleState") in {"discovered", "trained"}:
            return twin
    return None


def discover(
    frame: "pd.DataFrame",
    target: str | None = None,
    time: str | None = None,
    entity: str | None = None,
    kind: str | None = None,
    name: str | None = None,
    *,
    force: bool = False,
    transport: Transport,
    timeout: float = 3600.0,
) -> Graph:
    """Causal discovery straight from a DataFrame — no visible workspace ceremony.

    Artifacts live in the hidden ".sdk-scratch" workspace, keyed by a content
    hash of the frame. The twin models the uploaded source directly — no
    intermediate dataset is created. Re-running on identical data reuses the
    existing twin and its discovered graph instead of re-running discovery;
    calling .train() on the reused graph still retrains, so a rerun picks up
    engine fixes. force=True ignores the cache and discovers a fresh twin —
    the recovery path when an old model is corrupt or predates a fix.
    """
    import sys as _sys

    resolved_kind = infer_kind(time, entity, kind)
    workspace = scratch_workspace(transport)
    fingerprint = frame_fingerprint(frame)

    if not force:
        existing = _find_reusable_twin(workspace, fingerprint, resolved_kind, time, entity)
        if existing is not None:
            existing.requested_target = target
            print(
                f'Reusing twin "{existing.name}" already discovered for this exact data; '
                "pass force=True to re-run discovery from scratch.",
                file=_sys.stderr,
            )
            return existing.graph

    source = _ensure_source(workspace, frame, fingerprint)

    twin = workspace.create_twin(
        name or f"sdk-twin-{fingerprint}",
        kind=resolved_kind,
        source_id=source.id,
        time_column=time,
        environment_columns=[entity] if entity else None,
        tags=[f"sdk:{fingerprint}"],
    )
    twin.requested_target = target
    graph = twin.discover(timeout=timeout)
    return graph


def load_twin(path: str | Path, *, transport: Transport, timeout: float = 3600.0) -> Twin:
    """Import a .rctwin export zip into the scratch workspace and return the runnable twin."""
    blob = Path(path).read_bytes()
    workspace = scratch_workspace(transport)
    before = {twin.id for twin in workspace.twins}
    envelope = transport.request(
        "POST",
        f"/api/v1/workspaces/{workspace.id}/digital-twins/import",
        content=blob,
        headers={"Content-Type": "application/zip", "x-filename": Path(path).name if str(path).endswith(".zip") else "import.zip"},
    )
    job_id = str(envelope["data"]["jobId"])
    poll_job(transport, workspace.id, job_id, label="import twin", timeout=timeout)
    after = list(workspace.twins)
    fresh = [twin for twin in after if twin.id not in before]
    if fresh:
        return fresh[0]
    if after:
        return max(after, key=lambda twin: str(twin.doc.get("createdAt", "")))
    raise RootCauseError("Import finished but no twin appeared in the scratch workspace")
