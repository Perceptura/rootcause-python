import pytest

from rootcause.errors import RootCauseError
from rootcause.results import SampleDraws, SimulationResult
from rootcause.twin import Twin


def _twin(transport, kind: str) -> Twin:
    return Twin(
        transport,
        "ws1",
        {"id": "dt1", "name": "demo", "type": kind},
        {"id": "v1", "lifecycleState": "trained", "createdAt": "2026-01-01"},
    )


def test_sample_builds_intervention_spec_for_static(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/digital-twins/dt1/versions/v1/sample", {"data": {"columns": {"y": [1.0]}, "n": 1}})
    twin = _twin(transport, "static")

    draws = twin.sample(n=50, do={"price": 120}, where={"region": "US"}, seed=7)

    body = api.body_of("POST", "/sample")
    assert body["n"] == 50
    assert body["seed"] == 7
    assert body["spec"]["type"] == "intervention"
    assert body["spec"]["interventions"][0]["valueSpec"] == {"type": "set_value", "value": 120}
    assert body["spec"]["interventions"][0]["conditions"][0]["variable"] == "region"
    assert isinstance(draws, SampleDraws)


def test_sample_builds_panel_spec_with_environments(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/digital-twins/dt1/versions/v1/sample", {"data": {"environments": {"uk": {"y": [1.0]}}, "n": 1}})
    twin = _twin(transport, "multi-environment-temporal")

    twin.sample(environments=["uk"])

    body = api.body_of("POST", "/sample")
    assert body["spec"]["type"] == "panel_intervention"
    assert body["spec"]["environments"] == ["uk"]


def test_sample_environments_rejected_on_non_panel(transport):
    twin = _twin(transport, "static")
    with pytest.raises(RootCauseError):
        twin.sample(environments=["uk"])


def test_intervene_maps_scenario_type_per_kind(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/simulations", {"data": {"runId": "r1"}}, status=202)
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r1", {"data": {"status": "completed"}})

    for kind, expected in [
        ("static", "intervention"),
        ("temporal", "temporal_intervention"),
        ("multi-environment-temporal", "panel_intervention"),
    ]:
        api.requests.clear()
        result = _twin(transport, kind).intervene({"x": 1}, outcomes=["y"])
        assert isinstance(result, SimulationResult)
        assert api.body_of("POST", "/simulations")["scenario"]["type"] == expected


def test_intervene_without_metrics_raises_before_any_request(api, transport):
    twin = _twin(transport, "static")
    with pytest.raises(RootCauseError, match="metric"):
        twin.intervene({"x": 1})
    assert api.requests == []


def test_intervene_outcomes_build_mean_metrics(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/simulations", {"data": {"runId": "r9"}}, status=202)
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r9", {"data": {"status": "completed"}})

    _twin(transport, "static").intervene({"x": 1}, outcomes=["revenue"])

    scenario = api.body_of("POST", "/simulations")["scenario"]
    assert scenario["metrics"] == [
        {"name": "avg_revenue", "sqlQuery": 'SELECT AVG("revenue") AS value FROM df', "unit": "count", "higherIsBetter": True}
    ]


def test_forecast_rejects_static(transport):
    with pytest.raises(RootCauseError):
        _twin(transport, "static").forecast(horizon=12, targets=["y"])


def test_forecast_builds_panel_scenario(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/simulations", {"data": {"runId": "r2"}}, status=202)
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r2", {"data": {"status": "completed"}})

    _twin(transport, "multi-environment-temporal").forecast(horizon=24, targets=["revenue"], environments=["uk"])

    scenario = api.body_of("POST", "/simulations")["scenario"]
    assert scenario["type"] == "panel_forecast"
    assert scenario["forecastH"] == 24
    assert scenario["targetVars"] == ["revenue"]
    assert scenario["environments"] == ["uk"]


def test_failed_run_raises(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/simulations", {"data": {"runId": "r3"}}, status=202)
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r3", {"data": {"status": "failed", "error": "boom"}})

    from rootcause.errors import JobFailedError

    with pytest.raises(JobFailedError):
        _twin(transport, "static").intervene({"x": 1}, outcomes=["y"])


def test_sample_draws_flatten_environments():
    draws = SampleDraws({"environments": {"uk": {"y": [1.0, 2.0]}, "fr": {"y": [3.0]}}, "n": 2})
    frame = draws.to_frame()
    assert list(frame.columns) == ["environment", "y"]
    assert len(frame) == 3
    assert set(frame["environment"]) == {"uk", "fr"}


def test_train_on_trained_version_is_idempotent(api, transport, capsys):
    twin = _twin(transport, "static")
    result = twin.train()
    assert result is twin
    assert not any(r.method == "POST" for r in api.requests)
    assert "force=True" in capsys.readouterr().err


def test_forecast_aggregate_only_for_panel(api, transport):
    with pytest.raises(RootCauseError, match="aggregate"):
        _twin(transport, "temporal").forecast(horizon=6, targets=["y"], aggregate="sum")

    api.on("POST", "/api/v1/workspaces/ws1/simulations", {"data": {"runId": "r8"}}, status=202)
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r8", {"data": {"status": "completed"}})
    _twin(transport, "multi-environment-temporal").forecast(horizon=6, targets=["y"], aggregate="sum")
    assert api.body_of("POST", "/simulations")["scenario"]["aggregateMode"] == "sum"
