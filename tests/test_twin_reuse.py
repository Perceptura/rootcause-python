import pandas as pd
import pytest

from rootcause import direct
from rootcause.direct import frame_fingerprint


FRAME = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [2.0, 4.0, 6.0]})


def _seed_scratch(api, twins):
    api.on("GET", "/api/v1/workspaces", {"data": [{"id": "scratch1", "name": ".sdk-scratch"}]})
    api.on("GET", "/api/v1/workspaces/scratch1/digital-twins", {"data": twins})


def _twin_doc(twin_id, fingerprint, kind="static", created="2026-08-01"):
    return {"id": twin_id, "name": f"sdk-twin-{fingerprint}", "type": kind, "tags": [f"sdk:{fingerprint}"], "createdAt": created}


def test_identical_data_reuses_discovered_twin(api, transport, capsys):
    fingerprint = frame_fingerprint(FRAME)
    _seed_scratch(api, [_twin_doc("dtA", fingerprint)])
    api.on("GET", "/api/v1/workspaces/scratch1/digital-twins/dtA/versions", {"data": [
        {"id": "v1", "twinId": "dtA", "lifecycleState": "trained", "createdAt": "2026-08-01", "causalGraph": {"relationships": []}},
    ]})

    graph = direct.discover(FRAME, transport=transport)

    assert graph._twin.id == "dtA"
    assert not any(r.method == "POST" for r in api.requests), "reuse must not create or discover anything"
    assert "force=True" in capsys.readouterr().err


def test_force_bypasses_reuse_and_discovers_fresh(api, transport):
    fingerprint = frame_fingerprint(FRAME)
    _seed_scratch(api, [_twin_doc("dtA", fingerprint)])
    api.on("GET", "/api/v1/workspaces/scratch1/datasets", {"data": [
        {"id": "src1", "name": f"sdk-{fingerprint}"},
    ]})
    api.on("GET", "/api/v1/workspaces/scratch1/datasets/src1/schema", {"data": [{"field": "a"}, {"field": "b"}]})
    api.on("GET", "/api/v1/workspaces/scratch1/data-views", {"data": [
        {"id": "view1", "name": f"sdk-view-{fingerprint}"},
    ]})
    api.on("POST", "/api/v1/workspaces/scratch1/digital-twins", {"data": {"id": "dtNew", "name": "fresh", "type": "static"}}, status=201)
    api.on("GET", "/api/v1/workspaces/scratch1/digital-twins/dtNew/versions", {"data": [
        {"id": "v9", "twinId": "dtNew", "lifecycleState": "discovered", "createdAt": "2026-08-15"},
    ]})
    api.on("POST", "/api/v1/workspaces/scratch1/digital-twins/dtNew/versions/v9/discover", {"data": {"jobId": "j1"}}, status=202)
    api.on("GET", "/api/v1/workspaces/scratch1/jobs/j1", {"data": {"status": "completed"}})
    api.on("GET", "/api/v1/workspaces/scratch1/digital-twins/dtNew/versions/v9", {"data": {"id": "v9", "twinId": "dtNew", "lifecycleState": "discovered"}})

    graph = direct.discover(FRAME, force=True, transport=transport)

    assert graph._twin.id == "dtNew"
    assert any(r.method == "POST" and r.url.path.endswith("/digital-twins") for r in api.requests)


def test_kind_mismatch_does_not_reuse(api, transport):
    fingerprint = frame_fingerprint(FRAME)
    twins = [_twin_doc("dtStatic", fingerprint, kind="static")]
    _seed_scratch(api, twins)
    with pytest.raises(Exception):
        direct.discover(FRAME, time="a", transport=transport)
    assert not any(
        r.method == "GET" and "dtStatic/versions" in r.url.path for r in api.requests
    ), "a static twin must not even be considered for a temporal request"


def test_undiscovered_twin_is_not_reused(api, transport):
    fingerprint = frame_fingerprint(FRAME)
    _seed_scratch(api, [_twin_doc("dtEmpty", fingerprint)])
    api.on("GET", "/api/v1/workspaces/scratch1/digital-twins/dtEmpty/versions", {"data": [
        {"id": "v1", "twinId": "dtEmpty", "lifecycleState": "draft", "createdAt": "2026-08-01"},
    ]})
    result = direct._find_reusable_twin(
        direct.scratch_workspace(transport), fingerprint, "static", None, None
    )
    assert result is None
