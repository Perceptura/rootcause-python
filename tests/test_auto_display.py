"""Displayed result objects mount their app; nothing computes, nothing raises, static repr is the floor."""

import sys
import types

import pytest

import rootcause._display as display_mod
import rootcause.jupyter
from rootcause._display import auto_apps, show
from rootcause.graph import Graph
from rootcause.results import ScoreResult, SimulationResult, SweepResult
from rootcause.twin import Twin

WS = "ws1"


@pytest.fixture(autouse=True)
def reset_toggle():
    display_mod._state["enabled"] = None
    yield
    display_mod._state["enabled"] = None


@pytest.fixture
def fake_ipython(monkeypatch):
    shown = []
    fake = types.ModuleType("IPython.display")
    fake.display = lambda obj: shown.append(obj)
    fake.HTML = lambda html: ("HTML", html)
    monkeypatch.setitem(sys.modules, "IPython", types.ModuleType("IPython"))
    monkeypatch.setitem(sys.modules, "IPython.display", fake)
    return shown


@pytest.fixture
def mounts(monkeypatch):
    captured = []

    def fake_app(tool, arguments=None, *, theme="", height=480, transport=None, result=None):
        captured.append({"tool": tool, "arguments": arguments, "result": result})
        return f"widget:{tool}"

    monkeypatch.setattr(rootcause.jupyter, "app", fake_app)
    return captured


def test_auto_apps_defaults_on_and_reads_the_env(monkeypatch):
    assert auto_apps() is True
    monkeypatch.setenv("ROOTCAUSE_AUTO_APPS", "0")
    assert auto_apps() is False
    assert auto_apps(True) is True
    monkeypatch.delenv("ROOTCAUSE_AUTO_APPS")


def test_show_mounts_the_app(fake_ipython):
    show(object(), lambda: "the-widget")
    assert fake_ipython == ["the-widget"]


def test_show_degrades_to_the_static_repr_when_the_mount_fails(fake_ipython):
    class Obj:
        def _repr_html_(self):
            return "<b>static</b>"

    def broken():
        raise RuntimeError("no bundle")

    show(Obj(), broken)
    assert fake_ipython == [("HTML", "<b>static</b>")]


def test_show_respects_the_kill_switch(fake_ipython):
    auto_apps(False)
    mounted = []
    show(types.SimpleNamespace(_repr_html_=lambda: "<i>flat</i>"), lambda: mounted.append(1))
    assert mounted == []
    assert fake_ipython == [("HTML", "<i>flat</i>")]


def _sim(transport) -> SimulationResult:
    return SimulationResult(transport, WS, "run-7", {"status": "completed"}, {"type": "intervention"})


def test_simulation_result_mounts_the_run_readback(transport, mounts, fake_ipython):
    _sim(transport)._ipython_display_()
    assert mounts[-1]["tool"] == "get_digital_twin_run_result"
    assert mounts[-1]["arguments"] == {"workspaceId": WS, "runId": "run-7"}
    assert fake_ipython == ["widget:get_digital_twin_run_result"]


def test_sweep_result_mounts_the_curve(transport, mounts, fake_ipython):
    import pandas as pd

    frame = pd.DataFrame([{"causeValue": 1.0, "effectMean": 2.0}])
    frame.attrs["sweptVariable"] = "price"
    sweep = SweepResult(_sim(transport), "revenue", frame)

    assert list(sweep["causeValue"]) == [1.0]
    assert len(sweep) == 1

    sweep._ipython_display_()
    assert mounts[-1]["tool"] == "get_sweep_curve"
    assert mounts[-1]["arguments"] == {"workspaceId": WS, "digitalTwinRunId": "run-7", "metric": "revenue"}


def test_score_result_mounts_over_the_digest_it_already_has(transport, mounts, fake_ipython):
    score = ScoreResult(transport, WS, "run-9")
    score._first_page = {"data": {"digest": {"verdictCounts": {"achievable": 3}}}}

    score._ipython_display_()
    call = mounts[-1]
    assert call["tool"] == "score_twin_rows"
    assert call["result"]["structuredContent"] == {"scoreDigest": {"verdictCounts": {"achievable": 3}}}


def test_graph_mounts_the_console(transport, monkeypatch, fake_ipython):
    twin = Twin(transport, WS, {"id": "tw1", "name": "Churn", "type": "static"})
    twin._version_doc = {"id": "v1"}
    opened = []
    monkeypatch.setattr(Twin, "console", lambda self, **kwargs: opened.append(self.id) or "console-widget")

    Graph(twin)._ipython_display_()
    assert opened == ["tw1"]
    assert fake_ipython == ["console-widget"]


def test_env_subset_mounts_the_environment_listing(transport, mounts, fake_ipython):
    twin = Twin(transport, WS, {"id": "tw1", "name": "Panel", "type": "multi-environment-temporal"})
    twin._version_doc = {"id": "v1"}
    subset = twin.env("berlin")

    subset._ipython_display_()
    assert mounts[-1]["tool"] == "list_twin_environments"
    assert mounts[-1]["arguments"] == {"workspaceId": WS, "digitalTwinVersionId": "v1"}


def test_multi_target_forecast_frame_keeps_every_series(transport):
    from rootcause.results import ForecastResult

    result = ForecastResult(transport, WS, "run-f", {"status": "completed"}, {"type": "forecast"})
    result._results = {
        "1.0.0": {
            "results": {
                "Z": [{"timestamp": 1, "prediction": 1.0}, {"timestamp": 2, "prediction": 1.1}],
                "Y": [{"timestamp": 1, "prediction": 5.0}],
            },
            "changepoints": {"Z": [{"timestamp": 1, "kind": "trend"}]},
        }
    }

    frame = result.to_frame()
    assert sorted(frame["variable"].unique()) == ["Y", "Z"]
    assert len(frame) == 3


def test_single_target_forecast_frame_is_unchanged(transport):
    from rootcause.results import ForecastResult

    result = ForecastResult(transport, WS, "run-f", {"status": "completed"}, {"type": "forecast"})
    result._results = {"1.0.0": {"results": {"Z": [{"timestamp": 1, "prediction": 1.0}]}}}

    frame = result.to_frame()
    assert "variable" not in frame.columns
    assert list(frame["prediction"]) == [1.0]
