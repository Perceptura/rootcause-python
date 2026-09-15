"""Every key the SDK puts on a scenario must be one the backend declares.

R1 was a whole vocabulary the SDK sent and pydantic dropped: `rc.target`
built the union of the static and temporal target shapes, and each model
ignored the half it does not declare. An exact-dict assertion could not
catch that, because it asserts what the SDK builds and the SDK was the
thing under suspicion. These read the backend's models instead.

Skipped rather than failed when rootcause-backend is not beside this
checkout, so the suite still runs from a lone clone.
"""

import ast
from pathlib import Path

import pandas as pd
import pytest

import rootcause as rc
from rootcause.twin import Twin

MODELS = (
    Path(__file__).resolve().parents[2]
    / "rootcause-backend" / "src" / "rootcause" / "models" / "digital_twin_simulations.py"
)
pytestmark = pytest.mark.skipif(
    not MODELS.exists(), reason="rootcause-backend is not checked out beside this repo"
)


@pytest.fixture(scope="module")
def declared() -> dict[str, set[str]]:
    """Field names per model, read from the backend's source.

    Parsed rather than imported: this package is also called `rootcause`, so
    importing the backend's `rootcause.models` resolves to the SDK instead.
    """
    tree = ast.parse(MODELS.read_text(encoding="utf-8"))
    own: dict[str, set[str]] = {}
    bases: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        own[node.name] = {
            stmt.target.id
            for stmt in node.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        }
        bases[node.name] = [b.id for b in node.bases if isinstance(b, ast.Name)]

    def resolve(name: str, seen: frozenset[str] = frozenset()) -> set[str]:
        if name in seen:
            return set()
        fields = set(own.get(name, ()))
        for base in bases.get(name, []):
            fields |= resolve(base, seen | {name})
        return fields

    return {name: resolve(name) for name in own}


def _twin(transport, kind: str) -> Twin:
    return Twin(
        transport,
        "ws1",
        {"id": "dt1", "name": "demo", "type": kind},
        {"id": "v1", "lifecycleState": "trained", "createdAt": "2026-01-01"},
    )


@pytest.fixture
def run(api):
    api.on("POST", "/api/v1/workspaces/ws1/simulations", {"data": {"runId": "r1"}}, status=202)
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r1", {"data": {"status": "completed"}})
    return api


def _sent(api) -> dict:
    return api.body_of("POST", "/simulations")["scenario"]


REQUEST_MODEL = {
    "counterfactual": "MultiCounterfactualRequest",
    "temporal_counterfactual": "TemporalCounterfactualRequest",
    "panel_counterfactual": "PanelCounterfactualRequest",
    "causal_health_monitor": "CausalHealthMonitorRequest",
    "panel_causal_health_monitor": "PanelCausalHealthMonitorRequest",
}

TARGET_MODEL = {
    "counterfactual": "CounterfactualTarget",
    "temporal_counterfactual": "TemporalCounterfactualTarget",
    "panel_counterfactual": "TemporalCounterfactualTarget",
}


def _assert_no_stray_keys(sent: dict, fields: set[str], model: str, what: str) -> None:
    stray = sorted(set(sent) - fields)
    assert not stray, (
        f"{what} would silently drop {stray}: {model} declares {sorted(fields)}. "
        "pydantic's extra='ignore' means the request runs with different semantics from the call."
    )


@pytest.mark.parametrize(
    "kind,rows",
    [
        ("static", [{"tenure": 3}]),
        ("temporal", None),
        ("multi-environment-static", [{"tenure": 3}]),
        ("multi-environment-temporal", None),
    ],
)
def test_best_action_sends_no_key_the_backend_drops(run, transport, declared, kind, rows):
    timed = {"at": 1780272000000, "aggregation": "mean", "mode": "relative_percentage"} if rows is None else {}
    target = rc.target(
        "revenue", 1200.0, match="orMore", tolerance=5, tolerance_type="percentage", **timed
    )
    _twin(transport, kind).best_action([target], rows=rows, constraints={"a": {"type": "fixed"}}, max_changes=2)

    sent = _sent(run)
    request = REQUEST_MODEL[sent["type"]]
    _assert_no_stray_keys(sent, declared[request], request, f"best_action on {kind}")
    target_model = TARGET_MODEL[sent["type"]]
    for entry in sent["targets"]:
        _assert_no_stray_keys(entry, declared[target_model], target_model, f"rc.target for {sent['type']}")


@pytest.mark.parametrize("kind", ["temporal", "multi-environment-temporal"])
def test_monitor_sends_no_key_the_backend_drops(run, transport, declared, kind):
    _twin(transport, kind).monitor(
        pd.DataFrame([{"t": 1}]), start_step=1, end_step=4,
        target_fpr=0.01, parent_tolerance_sigma=1.5, auto_rca=False,
    )

    sent = _sent(run)
    request = REQUEST_MODEL[sent["type"]]
    _assert_no_stray_keys(sent, declared[request], request, f"monitor on {kind}")


@pytest.mark.parametrize("kind", ["static", "multi-environment-static"])
def test_a_static_twin_refuses_a_target_carrying_time(api, transport, declared, kind):
    with pytest.raises(rc.RootCauseError, match="only applies to temporal twins"):
        _twin(transport, kind).best_action(
            [rc.target("revenue", 1.0, at=1780272000000)], rows=[{"a": 1}]
        )
    assert api.requests == []


def test_every_match_mode_reaches_a_model_that_declares_it(declared):
    for name in ("CounterfactualTarget", "TemporalCounterfactualTarget"):
        assert "matchMode" in declared[name], (
            f"{name} must declare matchMode, or rc.target must stop sending it"
        )
