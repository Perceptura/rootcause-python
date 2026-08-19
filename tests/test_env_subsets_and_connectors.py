import pytest

from rootcause.errors import RootCauseError
from rootcause.twin import Twin
from rootcause.workspace import Connector

WS = "ws1"
TWIN_DOC = {"id": "tw1", "name": "Stores", "type": "multi-environment-temporal"}
VERSION = {"id": "v1", "version": "1.0.0", "lifecycleState": "trained"}

ENV_LISTING = {"data": {
    "environmentColumns": ["store"],
    "environments": [
        {"envKey": "london", "values": ["london"], "sampleSize": 30},
        {"envKey": "berlin", "values": ["berlin"], "sampleSize": 30},
        {"envKey": "paris", "values": ["paris"], "sampleSize": 30},
    ],
}}


def _twin(transport) -> Twin:
    twin = Twin(transport, WS, dict(TWIN_DOC))
    twin._version_doc = dict(VERSION)
    return twin


def test_env_subset_adjacency_resolves_names_and_carries_metadata(api, transport):
    api.on("GET", f"/api/v1/workspaces/{WS}/digital-twins/tw1/versions/v1/environments", ENV_LISTING)
    api.on("POST", f"/api/v1/workspaces/{WS}/digital-twins/tw1/versions/v1/graph/slice", {"data": {
        "causalGraph": [
            {"source": "price", "target": "demand", "strength": 0.9, "agreementRate": 1.0},
            {"source": "demand", "target": "revenue", "strength": 0.8, "agreementRate": 0.5},
        ],
        "nodes": [],
        "envCount": 2,
        "sampleSize": 60,
        "totalEnvCount": 3,
        "agreementThreshold": 0.5,
    }})

    frame = _twin(transport).env("london", "berlin").graph

    assert list(frame["source"]) == ["price", "demand"]
    assert frame.attrs["envCount"] == 2
    assert frame.attrs["totalEnvCount"] == 3

    body = api.body_of("POST", "/graph/slice")
    assert body["mode"] == "environments"
    assert body["environments"] == [{"store": "london"}, {"store": "berlin"}]


def test_env_subset_accepts_combos_and_threshold_without_listing(api, transport):
    api.on("POST", f"/api/v1/workspaces/{WS}/digital-twins/tw1/versions/v1/graph/slice", {"data": {
        "causalGraph": [], "nodes": [], "envCount": 1,
    }})

    _twin(transport).env({"store": "london"}).adjacency(agreement_threshold=0.8)

    body = api.body_of("POST", "/graph/slice")
    assert body["environments"] == [{"store": "london"}]
    assert body["agreementThreshold"] == 0.8
    # no listing round-trip needed when combos are explicit
    assert all("/environments" not in str(r.url) for r in api.requests)


def test_env_subset_unknown_name_is_a_clear_error(api, transport):
    api.on("GET", f"/api/v1/workspaces/{WS}/digital-twins/tw1/versions/v1/environments", ENV_LISTING)
    with pytest.raises(RootCauseError) as exc:
        _twin(transport).env("atlantis").combos()
    assert "atlantis" in str(exc.value)
    assert "london" in str(exc.value)


def test_env_subset_simulations_are_scoped(api, transport):
    api.on("POST", f"/api/v1/workspaces/{WS}/simulations", {"data": {"runId": "r1"}})
    api.on("GET", f"/api/v1/workspaces/{WS}/simulations/r1", {"data": {"status": "completed"}})

    _twin(transport).env("london").intervene({"price": {"type": "percentage", "value": -10}}, outcomes=["revenue"])

    body = api.body_of("POST", "/simulations")
    assert body["scenario"]["environments"] == ["london"]
    assert body["scenario"]["type"] == "panel_intervention"


def test_empty_env_subset_is_rejected(api, transport):
    with pytest.raises(RootCauseError):
        _twin(transport).env()


def test_connector_query_returns_a_frame(api, transport):
    api.on("POST", "/api/v1/connectors/conn-1/preview-query", {"data": {
        "success": True,
        "columns": [{"name": "region", "type": "String"}, {"name": "revenue", "type": "Float64"}],
        "rows": [["EMEA", "1200.5"], ["APAC", "900.0"]],
        "rowCount": 2,
    }})
    connector = Connector(transport, WS, {"id": "conn-1", "name": "Warehouse", "type": "Snowflake"})

    frame = connector.query("SELECT region, revenue FROM sales", limit=50, database="ANALYTICS")

    assert list(frame.columns) == ["region", "revenue"]
    assert len(frame) == 2
    body = api.body_of("POST", "/preview-query")
    assert body["config"]["query"] == "SELECT region, revenue FROM sales"
    assert body["config"]["database"] == "ANALYTICS"
    assert body["limit"] == 50


def test_connector_query_surfaces_database_errors(api, transport):
    api.on("POST", "/api/v1/connectors/conn-1/preview-query", {"data": {
        "success": False, "error": 'relation "salez" does not exist',
    }})
    connector = Connector(transport, WS, {"id": "conn-1", "name": "Warehouse", "type": "PostgreSQL"})

    with pytest.raises(RootCauseError) as exc:
        connector.query("SELECT * FROM salez")
    assert "salez" in str(exc.value)


def test_add_connector_wraps_credentials_with_type(api, transport):
    from rootcause.workspace import Workspace

    api.on("POST", "/api/v1/connectors", {"data": {"id": "conn-9", "name": "Warehouse", "type": "PostgreSQL"}})
    ws = Workspace(transport, {"id": WS, "name": "Demo"})

    connector = ws.add_connector("Warehouse", "PostgreSQL", host="db.internal", port=5432,
                                 database="warehouse", username="demo", password="secret")

    assert connector.id == "conn-9"
    body = api.body_of("POST", "/api/v1/connectors")
    assert body["credentials"]["type"] == "PostgreSQL"
    assert body["credentials"]["host"] == "db.internal"


def test_import_query_sends_flat_config_and_name(api, transport):
    api.on("POST", "/api/v1/connectors/conn-1/import", {"data": {"jobId": "job-1"}})
    api.on("GET", f"/api/v1/workspaces/{WS}/jobs/job-1", {"data": {"status": "completed", "domainEntityId": "src-1"}})
    api.on("GET", f"/api/v1/workspaces/{WS}/sources", {"data": [{"id": "src-1", "name": "sales-2026"}]})
    connector = Connector(transport, WS, {"id": "conn-1", "name": "Warehouse", "type": "Snowflake"})

    source = connector.import_query("SELECT * FROM sales", name="sales-2026")

    assert source.id == "src-1"
    body = api.body_of("POST", "/import")
    assert body["config"] == {"query": "SELECT * FROM sales"}
    assert body["datasetName"] == "sales-2026"


RESOLVED = {"data": {
    "environmentColumns": ["store"],
    "environments": [{"store": "london"}, {"store": "berlin"}],
    "envKeys": ["london", "berlin"],
    "sampleSize": 60,
    "totalEnvCount": 3,
}}


def test_env_where_compiles_tuples_and_resolves_server_side(api, transport):
    api.on("POST", f"/api/v1/workspaces/{WS}/digital-twins/tw1/versions/v1/environments/resolve", RESOLVED)

    subset = _twin(transport).env(where=[("revenue", "avg", ">", 400), ("region", "==", "EMEA")])
    frame = subset.environments

    body = api.body_of("POST", "/environments/resolve")
    assert body["statFilters"]["booleanOperator"] == "AND"
    assert body["statFilters"]["filters"] == [
        {"column": "revenue", "reduce": "mean", "comparisonOperator": "Greater than", "value": 400},
        {"column": "region", "reduce": "value", "comparisonOperator": "equal to", "value": "EMEA"},
    ]
    assert list(frame["envKey"]) == ["london", "berlin"]
    assert frame.attrs["totalEnvCount"] == 3


def test_env_where_scopes_simulations_to_the_matches(api, transport):
    api.on("POST", f"/api/v1/workspaces/{WS}/digital-twins/tw1/versions/v1/environments/resolve", RESOLVED)
    api.on("POST", f"/api/v1/workspaces/{WS}/simulations", {"data": {"runId": "r1"}})
    api.on("GET", f"/api/v1/workspaces/{WS}/simulations/r1", {"data": {"status": "completed"}})

    _twin(transport).env(where=[("revenue", "avg", ">", 400)]).intervene(
        {"price": {"type": "percentage", "value": -10}}, outcomes=["revenue"])

    body = api.body_of("POST", "/simulations")
    assert body["scenario"]["environments"] == ["london", "berlin"]


def test_env_where_feeds_the_graph_slice_with_resolved_combos(api, transport):
    api.on("POST", f"/api/v1/workspaces/{WS}/digital-twins/tw1/versions/v1/environments/resolve", RESOLVED)
    api.on("POST", f"/api/v1/workspaces/{WS}/digital-twins/tw1/versions/v1/graph/slice",
           {"data": {"causalGraph": [], "nodes": [], "envCount": 2}})

    _twin(transport).env(where=[("revenue", "avg", ">", 400)]).graph

    body = api.body_of("POST", "/graph/slice")
    assert body["mode"] == "environments"
    assert body["environments"] == [{"store": "london"}, {"store": "berlin"}]


def test_env_rejects_names_and_where_together(api, transport):
    with pytest.raises(RootCauseError):
        _twin(transport).env("london", where=[("revenue", "avg", ">", 400)])


def test_env_where_rejects_malformed_tuples(api, transport):
    with pytest.raises(RootCauseError):
        _twin(transport).env(where=[("revenue", ">")])
    with pytest.raises(RootCauseError):
        _twin(transport).env(where=[("revenue", "median", ">", 400)])
    with pytest.raises(RootCauseError):
        _twin(transport).env(where=[("revenue", "avg", "~=", 400)])


def test_named_subset_environments_frame(api, transport):
    api.on("GET", f"/api/v1/workspaces/{WS}/digital-twins/tw1/versions/v1/environments", ENV_LISTING)

    frame = _twin(transport).env("london").environments

    assert list(frame["envKey"]) == ["london"]
    assert list(frame["store"]) == ["london"]
