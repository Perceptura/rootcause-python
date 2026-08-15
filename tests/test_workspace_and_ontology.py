import pytest

from rootcause.errors import NotFoundInWorkspaceError
from rootcause.ontology import Ontology
from rootcause.workspace import Workspace


def _workspace(transport) -> Workspace:
    return Workspace(transport, {"id": "ws1", "name": "Demo"})


def test_collection_resolves_by_name_id_and_case(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/datasets", {"data": [
        {"id": "d1", "name": "Shipments"},
        {"id": "d2", "name": "Returns"},
    ]})
    workspace = _workspace(transport)
    assert workspace.sources["Shipments"].id == "d1"
    assert workspace.sources["d2"].name == "Returns"
    assert workspace.sources["shipments"].id == "d1"


def test_collection_miss_suggests_close_matches(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/datasets", {"data": [{"id": "d1", "name": "Shipments"}]})
    with pytest.raises(NotFoundInWorkspaceError) as exc:
        _workspace(transport).sources["Shipmets"]
    assert "Shipments" in str(exc.value)


def test_collection_completions_are_live_names(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/datasets", {"data": [{"id": "d1", "name": "Shipments"}]})
    assert _workspace(transport).sources._ipython_key_completions_() == ["Shipments"]


CONCEPTS = {"data": [
    {"id": "c_rev", "name": "revenue", "schemaType": "Number", "fieldMappings": []},
    {"id": "c_reg", "name": "region", "schemaType": "String", "fieldMappings": []},
]}


def test_ontology_query_compiles_names_operators_and_order(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/ontology/concepts", CONCEPTS)
    api.on("POST", "/api/v1/workspaces/ws1/ontology/query", {"data": {"rows": [], "nextStartKey": None}})

    ontology = Ontology(transport, "ws1")
    ontology.query(
        select=["revenue", "region"],
        where=[("region", "==", "US"), ("revenue", ">=", 100)],
        group_by=["region"],
        order_by="-revenue",
        aggregate={"revenue": "sum"},
        limit=50,
    )

    body = api.body_of("POST", "/ontology/query")
    query = body["query"]
    assert query["conceptIds"] == ["c_rev", "c_reg"]
    assert query["filters"] == [
        {"conceptId": "c_reg", "operator": "eq", "value": "US"},
        {"conceptId": "c_rev", "operator": "gte", "value": 100},
    ]
    assert query["groupBy"] == ["c_reg"]
    assert query["orderBy"] == [{"conceptId": "c_rev", "direction": "desc"}]
    assert query["aggregations"] == [{"conceptId": "c_rev", "function": "sum"}]
    assert query["limit"] == 50


def test_ontology_query_paginates_to_frame(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/ontology/concepts", CONCEPTS)
    pages = [
        {"data": {"rows": [{"revenue": 1}], "nextStartKey": 1}},
        {"data": {"rows": [{"revenue": 2}], "nextStartKey": None}},
    ]
    calls = {"n": 0}

    def handler(request):
        import httpx

        page = pages[min(calls["n"], 1)]
        calls["n"] += 1
        return httpx.Response(200, json=page)

    api.on("POST", "/api/v1/workspaces/ws1/ontology/query", handler)

    result = Ontology(transport, "ws1").query(select=["revenue"])
    frame = result.to_frame()
    assert list(frame["revenue"]) == [1, 2]
    assert calls["n"] == 2


def test_ontology_unknown_concept_suggests(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/ontology/concepts", CONCEPTS)
    with pytest.raises(NotFoundInWorkspaceError) as exc:
        Ontology(transport, "ws1").query(select=["revenu"])
    assert "revenue" in str(exc.value)


def test_ontology_ask_sends_prompt(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/ontology/query", {"data": {"rows": [], "nextStartKey": None, "query": {"conceptIds": []}}})
    result = Ontology(transport, "ws1").ask("average revenue in Florida")
    assert api.body_of("POST", "/ontology/query")["prompt"] == "average revenue in Florida"
    assert result.query == {"conceptIds": []}
