"""delete() issues the DELETE the public API has carried all along."""

from rootcause.twin import Twin
from rootcause.workspace import DataView, Source

WS = "ws1"


def _deletes(api):
    return [r.url.path for r in api.requests if r.method == "DELETE"]


def test_twin_delete(api, transport):
    api.on("DELETE", f"/api/v1/workspaces/{WS}/digital-twins/tw1", None, status=204)
    Twin(transport, WS, {"id": "tw1", "name": "Churn", "type": "static"}).delete()
    assert _deletes(api) == [f"/api/v1/workspaces/{WS}/digital-twins/tw1"]


def test_source_delete(api, transport):
    api.on("DELETE", f"/api/v1/workspaces/{WS}/sources/src1", None, status=204)
    Source(transport, WS, {"id": "src1"}).delete()
    assert _deletes(api) == [f"/api/v1/workspaces/{WS}/sources/src1"]


def test_dataset_delete(api, transport):
    api.on("DELETE", f"/api/v1/workspaces/{WS}/datasets/dv1", None, status=204)
    DataView(transport, WS, {"id": "dv1"}).delete()
    assert _deletes(api) == [f"/api/v1/workspaces/{WS}/datasets/dv1"]
