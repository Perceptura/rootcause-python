"""The scenario families that answer a question outright: predict, explain,
optimise, root_cause, anomalies.

Each family is spelled differently per twin kind, and the platform answers a
wrong spelling with a 422 rather than a wrong number, so the type mapping is
asserted for every kind rather than sampled.
"""

import pandas as pd
import pytest

import rootcause as rc
from rootcause.errors import InvalidArgumentError, RootCauseError
from rootcause.results import PredictionResult, SimulationResult
from rootcause.twin import Twin

KINDS = ["static", "temporal", "multi-environment-static", "multi-environment-temporal"]


def _twin(transport, kind: str = "static") -> Twin:
    return Twin(
        transport,
        "ws1",
        {"id": "dt1", "name": "demo", "type": kind},
        {"id": "v1", "lifecycleState": "trained", "createdAt": "2026-01-01"},
    )


@pytest.fixture
def run(api):
    """Accept any simulation submit and report it completed."""
    api.on("POST", "/api/v1/workspaces/ws1/simulations", {"data": {"runId": "r1"}}, status=202)
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r1", {"data": {"status": "completed"}})
    return api


def _scenario(api) -> dict:
    return api.body_of("POST", "/simulations")["scenario"]


# ── prediction ──────────────────────────────────────────────────────────────


def test_predict_builds_the_scenario_and_returns_a_prediction_result(run, transport):
    result = _twin(transport).predict([{"tenure": 3, "MonthlyCharges": 85.0}], targets=["Churn"])

    assert isinstance(result, PredictionResult)
    assert _scenario(run) == {
        "type": "prediction",
        "sample": [{"tenure": 3, "MonthlyCharges": 85.0}],
        "targetVars": ["Churn"],
        "confidenceLevel": 0.95,
    }


def test_predict_accepts_a_dataframe_and_a_confidence(run, transport):
    frame = pd.DataFrame([{"tenure": 3}, {"tenure": 40}])

    _twin(transport).predict(frame, targets=["Churn"], confidence=0.8)

    scenario = _scenario(run)
    assert scenario["sample"] == [{"tenure": 3}, {"tenure": 40}]
    assert scenario["confidenceLevel"] == 0.8


def test_predict_runs_on_a_multi_environment_static_twin(run, transport):
    _twin(transport, "multi-environment-static").predict([{"x": 1}], targets=["y"])

    # Prediction has no panel spelling: the platform's own wizard offers plain
    # "prediction" on a multi-environment static twin too.
    assert _scenario(run)["type"] == "prediction"


@pytest.mark.parametrize("kind", ["temporal", "multi-environment-temporal"])
def test_predict_rejects_temporal_twins_and_names_forecast(api, transport, kind):
    with pytest.raises(RootCauseError, match="forecast"):
        _twin(transport, kind).predict([{"x": 1}], targets=["y"])
    assert api.requests == []


def test_predict_infers_targets_from_variable_roles(run, transport):
    run.on(
        "GET",
        "/api/v1/workspaces/ws1/digital-twins/dt1/versions/v1/variable-roles",
        {"data": {"Churn": "target", "tenure": "input"}},
    )

    _twin(transport).predict([{"tenure": 3}])

    assert _scenario(run)["targetVars"] == ["Churn"]


@pytest.mark.parametrize(
    ("sample", "message"),
    [
        ([], "non-empty list"),
        (pd.DataFrame(), "no rows"),
        (["not a dict"], "dicts keyed by"),
    ],
)
def test_predict_rejects_unusable_samples_before_any_request(api, transport, sample, message):
    with pytest.raises(InvalidArgumentError, match=message):
        _twin(transport).predict(sample, targets=["y"])
    assert api.requests == []


def test_predict_rejects_a_confidence_outside_zero_to_one(api, transport):
    with pytest.raises(InvalidArgumentError, match="confidence"):
        _twin(transport).predict([{"x": 1}], targets=["y"], confidence=95)
    assert api.requests == []


def test_prediction_frame_indexes_rows_and_names_targets(api, transport):
    payload = {
        "1.0.0": {
            "results": {
                "Churn": [
                    {"prediction": "No", "lowerBound": [0.35], "upperBound": [0.49]},
                    {"prediction": "Yes", "lowerBound": [0.61], "upperBound": [0.74]},
                ],
                "TotalCharges": [{"prediction": 255.0}, {"prediction": 3400.0}],
            }
        }
    }
    api.on("GET", "/api/v1/workspaces/ws1/simulations/rp/results", {"data": payload})

    frame = PredictionResult(transport, "ws1", "rp", {"status": "completed"}).to_frame()

    assert list(frame.columns[:3]) == ["variable", "row", "prediction"]
    assert frame["row"].tolist() == [0, 1, 0, 1]
    assert set(frame["variable"]) == {"Churn", "TotalCharges"}


def test_prediction_frame_keeps_row_alignment_for_a_single_target(api, transport):
    payload = {"1.0.0": {"results": {"Churn": [{"prediction": "No"}, {"prediction": "Yes"}]}}}
    api.on("GET", "/api/v1/workspaces/ws1/simulations/rp/results", {"data": payload})

    frame = PredictionResult(transport, "ws1", "rp", {"status": "completed"}).to_frame()

    # One target needs no `variable` column, but the row index still has to be
    # there: it is the only thing tying a prediction to the record it answers.
    assert list(frame.columns) == ["row", "prediction"]
    assert frame["row"].tolist() == [0, 1]


def test_prediction_frame_labels_environments(api, transport):
    payload = {
        "1.0.0": {
            "environmentResults": {
                "uk": {"results": {"y": [{"prediction": 1.0}]}},
                "fr": {"results": {"y": [{"prediction": 2.0}]}},
            }
        }
    }
    api.on("GET", "/api/v1/workspaces/ws1/simulations/rp/results", {"data": payload})

    frame = PredictionResult(transport, "ws1", "rp", {"status": "completed"}).to_frame()

    assert set(frame["environment"]) == {"uk", "fr"}
    assert frame["row"].tolist() == [0, 0]


# ── explanation ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("static", "explanation"),
        ("temporal", "temporal_explanation"),
        ("multi-environment-static", "panel_explanation"),
        ("multi-environment-temporal", "panel_explanation"),
    ],
)
def test_explain_maps_the_scenario_type_per_kind(run, transport, kind, expected):
    result = _twin(transport, kind).explain(effect="Churn")

    assert isinstance(result, SimulationResult)
    assert _scenario(run)["type"] == expected


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"effect": "Churn"}, "discovery"),
        ({"cause": "Contract"}, "impact"),
        ({"cause": "Contract", "effect": "Churn"}, "directional"),
    ],
)
def test_explain_infers_the_mode_from_the_variables_named(run, transport, kwargs, expected):
    _twin(transport).explain(**kwargs)

    scenario = _scenario(run)
    assert scenario["explanationMode"] == expected
    assert scenario["causeVariable"] == kwargs.get("cause")
    assert scenario["effectVariable"] == kwargs.get("effect")


def test_explain_carries_environments_on_a_panel_twin(run, transport):
    _twin(transport, "multi-environment-temporal").explain(effect="y", environments=["uk"])

    assert _scenario(run)["environments"] == ["uk"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "variable to explain"),
        ({"mode": "directional", "cause": "x"}, "effect="),
        ({"mode": "impact", "effect": "y"}, "cause="),
        ({"effect": "y", "mode": "vibes"}, "mode="),
        ({"effect": "y", "environments": ["uk"]}, "panel twins"),
    ],
)
def test_explain_rejects_incoherent_arguments_before_any_request(api, transport, kwargs, message):
    with pytest.raises((RootCauseError, InvalidArgumentError), match=message):
        _twin(transport).explain(**kwargs)
    assert api.requests == []


# ── optimisation ────────────────────────────────────────────────────────────


def _objective() -> dict:
    return rc.objective("Churn rate", 'SELECT AVG("Churn") AS value FROM df', "minimise")


def test_objective_builds_the_payload_and_accepts_either_spelling():
    assert _objective() == {
        "direction": "minimise",
        "variable": "Churn rate",
        "metricSqlQuery": 'SELECT AVG("Churn") AS value FROM df',
    }
    assert rc.objective("R", "SELECT 1 AS value FROM df", "maximize")["direction"] == "maximise"
    assert rc.objective("R", "SELECT 1 AS value FROM df", unit="USD", weight=2)["weight"] == 2.0


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((" ", "SELECT 1 AS value FROM df"), "needs a name"),
        (("R", "revenue"), "SELECT"),
        (("R", "SELECT 1 AS value FROM df", "sideways"), "maximise or minimise"),
    ],
)
def test_objective_rejects_what_the_optimizer_cannot_read(args, message):
    with pytest.raises(InvalidArgumentError, match=message):
        rc.objective(*args)


def test_optimise_builds_the_static_scenario(run, transport):
    _twin(transport).optimise([_objective()], decision_vars=["Contract"], max_changes=2)

    assert _scenario(run) == {
        "type": "optimisation",
        "objectives": [_objective()],
        "decisionVars": ["Contract"],
        "interventionCountConfig": {"maxInterventions": 2},
    }


def test_optimise_carries_constraints_when_given(run, transport):
    _twin(transport).optimise(
        [_objective()],
        decision_vars=["MonthlyCharges"],
        variable_constraints=[{"variable": "MonthlyCharges", "type": "range", "minValue": 20, "maxValue": 90}],
        metric_constraints=[{"metricName": "revenue", "sqlQuery": "SELECT 1 AS value FROM df", "constraintType": "min_value", "value": 10}],
    )

    scenario = _scenario(run)
    assert scenario["variableConstraints"][0]["variable"] == "MonthlyCharges"
    assert scenario["metricConstraints"][0]["constraintType"] == "min_value"


def test_optimise_needs_a_horizon_on_a_temporal_twin(api, transport):
    with pytest.raises(RootCauseError, match="horizon="):
        _twin(transport, "temporal").optimise([_objective()], decision_vars=["x"])
    assert api.requests == []


def test_optimise_takes_the_horizon_on_temporal_and_panel_twins(run, transport):
    _twin(transport, "temporal").optimise([_objective()], decision_vars=["x"], horizon=12)
    assert _scenario(run) == {
        "type": "temporal_optimisation",
        "objectives": [_objective()],
        "decisionVars": ["x"],
        "forecastHorizon": 12,
    }

    run.requests.clear()
    _twin(transport, "multi-environment-temporal").optimise(
        [_objective()], decision_vars=["x"], horizon=6, environments=["uk"]
    )
    scenario = _scenario(run)
    assert scenario["type"] == "panel_optimisation"
    assert scenario["forecastHorizon"] == 6
    assert scenario["environments"] == ["uk"]


def test_optimise_refuses_a_horizon_a_static_twin_cannot_use(api, transport):
    # A multi-environment static twin optimizes one period; the platform's own
    # wizard strips forecastHorizon off that scenario rather than honouring it.
    with pytest.raises(RootCauseError, match="temporal twins"):
        _twin(transport, "multi-environment-static").optimise([_objective()], decision_vars=["x"], horizon=6)
    assert api.requests == []


def test_optimise_runs_a_multi_environment_static_twin_without_a_horizon(run, transport):
    _twin(transport, "multi-environment-static").optimise([_objective()], decision_vars=["x"])

    scenario = _scenario(run)
    assert scenario["type"] == "panel_optimisation"
    assert "forecastHorizon" not in scenario


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (([], ["x"]), "at least one objective"),
        (([_objective()], []), "decision variable"),
        (([{"variable": "R"}], ["x"]), "rc.objective"),
    ],
)
def test_optimise_rejects_an_unusable_setup_before_any_request(api, transport, args, message):
    with pytest.raises(RootCauseError, match=message):
        _twin(transport).optimise(*args)
    assert api.requests == []


# ── root cause and anomaly scans ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("static", "root_cause_analysis"),
        ("temporal", "temporal_root_cause_analysis"),
        ("multi-environment-static", "static_panel_root_cause_analysis"),
        ("multi-environment-temporal", "panel_root_cause_analysis"),
    ],
)
def test_root_cause_maps_the_scenario_type_per_kind(run, transport, kind, expected):
    _twin(transport, kind).root_cause("Churn", [{"Churn": 1}])

    scenario = _scenario(run)
    assert scenario["type"] == expected
    assert scenario["targetVariable"] == "Churn"
    assert scenario["samples"] == [{"Churn": 1}]
    assert scenario["targetFpr"] == 0.005


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("static", "anomaly_detection"),
        ("temporal", "temporal_anomaly_detection"),
        ("multi-environment-static", "static_panel_anomaly_detection"),
        ("multi-environment-temporal", "panel_anomaly_detection"),
    ],
)
def test_anomalies_maps_the_scenario_type_per_kind(run, transport, kind, expected):
    _twin(transport, kind).anomalies([{"x": 1}])

    assert _scenario(run)["type"] == expected


def test_per_environment_samples_become_panel_samples(run, transport):
    _twin(transport, "multi-environment-temporal").anomalies({"uk": [{"x": 1}], "fr": [{"x": 2}]})

    scenario = _scenario(run)
    assert scenario["panelSamples"] == {"uk": [{"x": 1}], "fr": [{"x": 2}]}
    assert "samples" not in scenario


def test_a_flat_sample_list_is_shared_across_a_panel_twin(run, transport):
    _twin(transport, "multi-environment-temporal").anomalies([{"x": 1}], environments=["uk"])

    scenario = _scenario(run)
    assert scenario["samples"] == [{"x": 1}]
    assert scenario["environments"] == ["uk"]


def test_root_cause_carries_a_timestep_on_a_temporal_twin(run, transport):
    _twin(transport, "temporal").root_cause("y", [{"y": 1}], timestep=17, target_fpr=0.01)

    scenario = _scenario(run)
    assert scenario["anomalyTimestep"] == 17
    assert scenario["targetFpr"] == 0.01


def test_anomalies_carries_a_step_window_on_a_temporal_twin(run, transport):
    _twin(transport, "temporal").anomalies([{"y": 1}], start_step=4, end_step=9)

    scenario = _scenario(run)
    assert scenario["startStep"] == 4
    assert scenario["endStep"] == 9


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda t: t.root_cause("", [{"x": 1}]), "target="),
        (lambda t: t.root_cause("y", [{"x": 1}], timestep=3), "temporal twins"),
        (lambda t: t.root_cause("y", {"uk": [{"x": 1}]}), "panel twins"),
        (lambda t: t.root_cause("y", [{"x": 1}], target_fpr=0.5), "target_fpr="),
        (lambda t: t.anomalies([{"x": 1}], start_step=2), "temporal twins"),
        (lambda t: t.anomalies([{"x": 1}], environments=["uk"]), "panel twins"),
    ],
)
def test_diagnosis_verbs_reject_arguments_a_static_twin_cannot_use(api, transport, call, message):
    with pytest.raises((RootCauseError, InvalidArgumentError), match=message):
        call(_twin(transport))
    assert api.requests == []


def test_an_empty_environment_mapping_is_refused(api, transport):
    with pytest.raises(InvalidArgumentError, match="no environments"):
        _twin(transport, "multi-environment-temporal").anomalies({})
    assert api.requests == []


def test_every_kind_has_a_name_for_every_family(transport):
    from rootcause.twin import ANOMALY_TYPES, EXPLANATION_TYPES, OPTIMISATION_TYPES, ROOT_CAUSE_TYPES

    for family in (EXPLANATION_TYPES, OPTIMISATION_TYPES, ROOT_CAUSE_TYPES, ANOMALY_TYPES):
        assert sorted(family) == sorted(KINDS)


def test_an_unknown_kind_says_so_rather_than_guessing(api, transport):
    twin = Twin(transport, "ws1", {"id": "dt1", "name": "demo", "type": "quantum"}, {"id": "v1"})

    with pytest.raises(RootCauseError, match="quantum"):
        twin.explain(effect="y")
    assert api.requests == []
