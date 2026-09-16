"""delete() issues the DELETE the public API has carried all along."""

import pytest

from rootcause.errors import RootCauseApiError
from rootcause.twin import Twin
from rootcause.workspace import Dataset, Source

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
    Dataset(transport, WS, {"id": "dv1"}).delete()
    assert _deletes(api) == [f"/api/v1/workspaces/{WS}/datasets/dv1"]


def test_source_delete_does_not_force_by_default(api, transport):
    api.on("DELETE", f"/api/v1/workspaces/{WS}/sources/src1", None, status=204)
    Source(transport, WS, {"id": "src1"}).delete()
    assert api.requests[-1].url.params.get("force") is None


def test_source_delete_force_is_sent_as_a_query_param(api, transport):
    api.on("DELETE", f"/api/v1/workspaces/{WS}/sources/src1", None, status=204)
    Source(transport, WS, {"id": "src1"}).delete(force=True)
    assert api.requests[-1].url.params["force"] == "true"


def test_source_delete_blocked_by_a_twin_names_it(api, transport):
    api.on(
        "DELETE",
        f"/api/v1/workspaces/{WS}/sources/src1",
        {
            "title": "Conflict",
            "status": 409,
            "detail": "This source is the training data of digital twin 'Demand'. Deleting it leaves them without history, backtests or a relink target — delete those twins first, or repeat this request with force=true.",
            "blockingDigitalTwins": [{"id": "tw1", "name": "Demand", "workspaceId": WS}],
        },
        status=409,
    )
    with pytest.raises(RootCauseApiError) as caught:
        Source(transport, WS, {"id": "src1"}).delete()
    assert caught.value.status == 409
    assert "'Demand'" in str(caught.value)
    assert caught.value.body["blockingDigitalTwins"] == [{"id": "tw1", "name": "Demand", "workspaceId": WS}]
