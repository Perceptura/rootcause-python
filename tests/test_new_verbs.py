import pandas as pd
import pytest

import rootcause as rc
from rootcause.errors import RootCauseError
from rootcause.results import ScoreResult, UpdateResult
from rootcause.twin import Twin
from rootcause.workspace import Workspace

WS = "ws1"
TWIN_DOC = {"id": "tw1", "name": "Churn", "type": "static"}
VERSION = {"id": "v1", "version": "1.0.0", "lifecycleState": "trained"}


def _twin(transport) -> Twin:
    twin = Twin(transport, WS, dict(TWIN_DOC))
    twin._version_doc = dict(VERSION)
    return twin


def _stub_versions(api):
    api.on("GET", f"/api/v1/workspaces/{WS}/digital-twins/tw1/versions", {"data": [dict(VERSION)]})


def test_whoami_reads_me(api, transport, monkeypatch):
    api.on("GET", "/api/v1/me", {"data": {"userId": "u1", "scopes": ["sources:read"], "authType": "apiKey"}})
    monkeypatch.setattr(rc, "_transport", lambda: transport)
    identity = rc.whoami()
    assert identity["userId"] == "u1"
    assert identity["authType"] == "apiKey"


def test_new_version_derives_and_pins(api, transport):
    _stub_versions(api)
    api.on("POST", "/api/v1/workspaces/ws1/digital-twins/tw1/versions", {"data": {"id": "v2", "version": "1.0.1"}})
    api.on("GET", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v2", {"data": {"id": "v2", "version": "1.0.1", "lifecycleState": "resolved"}})

    fresh = _twin(transport).new_version(bump="minor")

    assert fresh.version_id == "v2"
    body = api.body_of("POST", "/versions")
    assert body == {"bump": "minor"}


def test_update_returns_terminal_status(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v1/update-model", {"data": {"jobId": "ma-run-v1"}})
    api.on("GET", "/api/v1/workspaces/ws1/jobs/ma-run-v1", {"data": {
        "status": "completed",
        "metadata": {"status": "committed", "rowsAssimilated": 120},
    }})
    api.on("GET", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v1", {"data": dict(VERSION)})

    result = _twin(transport).update()

    assert isinstance(result, UpdateResult)
    assert result.status == "committed"
    assert result.rows_assimilated == 120
    assert result.retrain_required is False


def test_update_surfaces_retrain_required_without_raising(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v1/update-model", {"data": {"jobId": "ma-run-v1"}})
    api.on("GET", "/api/v1/workspaces/ws1/jobs/ma-run-v1", {"data": {
        "status": "completed",
        "metadata": {"status": "retrain_required"},
    }})
    api.on("GET", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v1", {"data": dict(VERSION)})

    result = _twin(transport).update()

    assert result.retrain_required is True


def test_environments_frame(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v1/environments", {"data": {
        "environmentColumns": ["region"],
        "environments": [
            {"envKey": "region=EMEA", "values": {"region": "EMEA"}, "sampleSize": 900},
            {"envKey": "region=APAC", "values": {"region": "APAC"}, "sampleSize": 400},
        ],
    }})

    frame = _twin(transport).environments

    assert list(frame["envKey"]) == ["region=EMEA", "region=APAC"]
    assert list(frame["sampleSize"]) == [900, 400]


def test_score_polls_run_and_pages_rows(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v1/score", {"data": {"runId": "r9"}})
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r9", {"data": {"status": "completed"}})
    pages = [
        {
            "data": {
                "digest": {"verdictCounts": {"flips": 2}},
                "rows": [{"index": 0, "flip": {"variable": "contract"}}],
            },
            "pagination": {"cursor": "MQ", "hasMore": True, "total": 2},
        },
        {
            "data": {"digest": {"verdictCounts": {"flips": 2}}, "rows": [{"index": 1, "flip": None}]},
            "pagination": {"hasMore": False, "total": 2},
        },
    ]
    calls = {"n": 0}

    def handler(request):
        import httpx

        page = pages[min(calls["n"], 1)]
        calls["n"] += 1
        return httpx.Response(200, json=page)

    api.on("GET", "/api/v1/workspaces/ws1/simulations/r9/score", handler)

    result = _twin(transport).score(
        pd.DataFrame([{"tenure": 3}, {"tenure": 9}]),
        targets=[{"variable": "churn", "value": "no"}],
    )

    assert isinstance(result, ScoreResult)
    body = api.body_of("POST", "/score")
    assert body["rows"] == [{"tenure": 3}, {"tenure": 9}]
    assert body["targets"] == [{"variable": "churn", "value": "no"}]
    assert body["maxChanges"] == 3
    assert result.digest == {"verdictCounts": {"flips": 2}}
    frame = result.to_frame()
    assert len(frame) == 2


def test_range_constructor_shapes_the_value_spec():
    assert rc.range(15, 30) == {"type": "range", "from": 15.0, "to": 30.0}
    assert rc.range(steps=10) == {"type": "range", "steps": 10}


def test_sweep_lists_metrics_when_ambiguous(api, transport):
    from rootcause.results import SimulationResult

    api.on("GET", "/api/v1/workspaces/ws1/simulations/r1/sweep", {"data": {"metrics": ["Revenue", "Cost"]}})
    result = SimulationResult(transport, WS, "r1", {"status": "completed"}, {})
    with pytest.raises(RootCauseError) as exc:
        result.sweep()
    assert "Revenue" in str(exc.value)


def test_sweep_returns_the_curve(api, transport):
    from rootcause.results import SimulationResult

    def handler(request):
        import httpx

        assert request.url.params["metric"] == "Revenue"
        return httpx.Response(200, json={"data": {
            "metric": "Revenue",
            "sweptVariable": "price",
            "points": [
                {"causeValue": 15.0, "mean": 100.0},
                {"causeValue": 30.0, "mean": 130.0},
            ],
        }})

    api.on("GET", "/api/v1/workspaces/ws1/simulations/r1/sweep", handler)
    frame = SimulationResult(transport, WS, "r1", {"status": "completed"}, {}).sweep("Revenue")
    assert list(frame["causeValue"]) == [15.0, 30.0]
    assert frame.attrs["sweptVariable"] == "price"


def test_create_twin_rejects_both_ids(api, transport):
    workspace = Workspace(transport, {"id": WS, "name": "Demo"})
    with pytest.raises(RootCauseError):
        workspace.create_twin("T", dataset_id="d1", source_id="s1")


def test_create_twin_sends_source_id(api, transport):
    api.on("POST", f"/api/v1/workspaces/{WS}/digital-twins", {"data": {"id": "tw2", "name": "T", "type": "static"}})
    workspace = Workspace(transport, {"id": WS, "name": "Demo"})
    workspace.create_twin("T", source_id="s1")
    body = api.body_of("POST", "/digital-twins")
    assert body["sourceId"] == "s1"
    assert "datasetId" not in body


def test_twin_source_resolves_the_backing_source(api, transport):
    twin = Twin(transport, WS, dict(TWIN_DOC))
    twin._version_doc = {**VERSION, "sourceId": "src-7"}
    api.on("GET", f"/api/v1/workspaces/{WS}/sources/src-7", {"data": {"id": "src-7", "name": "uploads"}})

    source = twin.source

    assert source is not None
    assert source.id == "src-7"
    assert source.name == "uploads"


def test_twin_source_is_none_for_dataset_backed_versions(api, transport):
    assert _twin(transport).source is None


def test_source_extend_sends_parquet_rows(api, transport):
    import pyarrow.parquet as pq
    from io import BytesIO

    from rootcause.workspace import Source

    received: list[bytes] = []

    def handler(request):
        import httpx

        received.append(request.content)
        return httpx.Response(200, json={"data": {"status": "Done"}})

    api.on("POST", f"/api/v1/workspaces/{WS}/sources/src-7/extend", handler)
    source = Source(transport, WS, {"id": "src-7", "name": "uploads"})

    source.extend(pd.DataFrame([{"a": 1, "b": 2.5}, {"a": 2, "b": 3.5}]))

    table = pq.read_table(BytesIO(received[0]))
    assert table.num_rows == 2
    assert table.column_names == ["a", "b"]


def test_retrain_is_new_version_plus_train(api, transport):
    _stub_versions(api)
    api.on("POST", "/api/v1/workspaces/ws1/digital-twins/tw1/versions", {"data": {"id": "v2", "version": "1.0.1"}})
    api.on("GET", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v2", {"data": {"id": "v2", "version": "1.0.1", "lifecycleState": "resolved"}})
    api.on("POST", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v2/train", {"data": {"jobId": "mt-run-v2"}})
    api.on("GET", "/api/v1/workspaces/ws1/jobs/mt-run-v2", {"data": {"status": "completed"}})

    trained = _twin(transport).retrain()

    assert trained.version_id == "v2"


def test_roles_reads_the_variable_roles(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v1/variable-roles",
           {"data": {"sources": ["price"], "targets": ["revenue"]}})
    assert _twin(transport).roles == {"sources": ["price"], "targets": ["revenue"]}


def test_set_roles_merges_the_unspecified_side(api, transport):
    twin = _twin(transport)
    twin._version_doc = {**VERSION, "inputFields": [
        {"field": "price"}, {"field": "demand"}, {"field": "revenue"}]}
    api.on("GET", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v1/variable-roles",
           {"data": {"sources": ["price", "demand"], "targets": ["demand"]}})
    api.on("PUT", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v1/variable-roles",
           {"data": {"sources": ["price", "demand"], "targets": ["revenue"]}})
    api.on("GET", "/api/v1/workspaces/ws1/digital-twins/tw1/versions/v1", {"data": dict(VERSION)})

    stored = twin.set_roles(targets=["revenue"])

    body = api.body_of("PUT", "/variable-roles")
    assert body == {"sources": ["price", "demand"], "targets": ["revenue"]}
    assert stored["targets"] == ["revenue"]


def test_set_roles_rejects_unknown_variables(api, transport):
    twin = _twin(transport)
    twin._version_doc = {**VERSION, "inputFields": [{"field": "price"}, {"field": "revenue"}]}
    with pytest.raises(RootCauseError) as exc:
        twin.set_roles(targets=["revenu"], sources=["price"])
    assert "revenu" in str(exc.value)
    assert "revenue" in str(exc.value)


def test_set_roles_requires_something(api, transport):
    with pytest.raises(RootCauseError):
        _twin(transport).set_roles()
