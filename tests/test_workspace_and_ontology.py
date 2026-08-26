import pytest

from rootcause.errors import AnchorSqlError, InvalidArgumentError, NotFoundInWorkspaceError, RootCauseError
from rootcause.ontology import Ontology
from rootcause.workspace import Workspace


def _workspace(transport) -> Workspace:
    return Workspace(transport, {"id": "ws1", "name": "Demo"})


def test_collection_resolves_by_name_id_and_case(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/sources", {"data": [
        {"id": "d1", "name": "Shipments"},
        {"id": "d2", "name": "Returns"},
    ]})
    workspace = _workspace(transport)
    assert workspace.sources["Shipments"].id == "d1"
    assert workspace.sources["d2"].name == "Returns"
    assert workspace.sources["shipments"].id == "d1"


def test_collection_miss_suggests_close_matches(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/sources", {"data": [{"id": "d1", "name": "Shipments"}]})
    with pytest.raises(NotFoundInWorkspaceError) as exc:
        _workspace(transport).sources["Shipmets"]
    assert "Shipments" in str(exc.value)


def test_collection_completions_are_live_names(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/sources", {"data": [{"id": "d1", "name": "Shipments"}]})
    assert _workspace(transport).sources._ipython_key_completions_() == ["Shipments"]


ROWS_PAGE = {"data": {
    "ok": True,
    "kind": "rows",
    "sql": 'SELECT "revenue"',
    "columns": ["revenue"],
    "rows": [{"revenue": 1}],
    "rowCount": 1,
    "totalRowCount": 134,
    "truncated": False,
    "units": {"revenue": "usd"},
    "plan": {"chips": [{"kind": "spine", "label": "orders"}], "joinPlan": [], "strategy": "single"},
    "warnings": ["joined over a low-cardinality key"],
}}


def test_ontology_sql_sends_statement_and_limit(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/ontology/query", ROWS_PAGE)
    result = Ontology(transport, "ws1").sql('SELECT "revenue"', limit=50)
    body = api.body_of("POST", "/ontology/query")
    assert body == {"anchorSql": 'SELECT "revenue"', "limit": 50, "projectionMode": "related"}
    assert result.kind == "rows"
    assert result.rows == [{"revenue": 1}]
    assert result.columns == ["revenue"]
    assert result.units == {"revenue": "usd"}
    assert result.row_count == 1
    assert result.total_row_count == 134
    assert result.next_start_key is None
    assert result.plan["strategy"] == "single"
    assert result.warnings == ["joined over a low-cardinality key"]
    assert result.statement == 'SELECT "revenue"'


def test_ontology_sql_start_key_resumes(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/ontology/query", ROWS_PAGE)
    Ontology(transport, "ws1").sql('SELECT "revenue"', start_key=200)
    assert api.body_of("POST", "/ontology/query")["startKey"] == 200


def test_ontology_sql_forwards_projection_mode(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/ontology/query", ROWS_PAGE)
    Ontology(transport, "ws1").sql('SELECT "revenue"', projection_mode="minimal")
    assert api.body_of("POST", "/ontology/query")["projectionMode"] == "minimal"


def test_ontology_sql_rejects_unknown_projection_mode(api, transport):
    with pytest.raises(InvalidArgumentError, match="projection_mode"):
        Ontology(transport, "ws1").sql('SELECT "revenue"', projection_mode="wide")
    assert api.requests == []


def test_ontology_sql_paginates_to_frame(api, transport):
    pages = [
        {"data": {"ok": True, "kind": "rows", "columns": ["revenue"], "rows": [{"revenue": 1}], "nextStartKey": 1}},
        {"data": {"ok": True, "kind": "rows", "columns": ["revenue"], "rows": [{"revenue": 2}]}},
    ]
    calls = {"n": 0}

    def handler(request):
        import httpx

        page = pages[min(calls["n"], 1)]
        calls["n"] += 1
        return httpx.Response(200, json=page)

    api.on("POST", "/api/v1/workspaces/ws1/ontology/query", handler)

    frame = Ontology(transport, "ws1").sql('SELECT "revenue"').to_frame()
    assert list(frame["revenue"]) == [1, 2]
    assert calls["n"] == 2
    import json

    second_body = json.loads(api.requests[-1].content.decode())
    assert second_body["startKey"] == 1
    assert second_body["anchorSql"] == 'SELECT "revenue"'


def test_ontology_sql_metadata_commands_come_back_tabular(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/ontology/query", {"data": {
        "ok": True,
        "kind": "metadata",
        "command": "SHOW CONCEPTS",
        "columns": ["name", "type"],
        "rows": [{"name": "revenue", "type": "Number"}, {"name": "region", "type": "String"}],
    }})
    result = Ontology(transport, "ws1").sql("SHOW CONCEPTS")
    assert result.kind == "metadata"
    assert result.statement == "SHOW CONCEPTS"
    frame = result.to_frame()
    assert list(frame.columns) == ["name", "type"]
    assert list(frame["name"]) == ["revenue", "region"]


def test_ontology_sql_error_arm_raises_with_candidates(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/ontology/query", {"data": {
        "ok": False,
        "error": {
            "code": "unknown_concept",
            "message": 'Unknown concept "revenu".',
            "span": [7, 15],
            "candidates": [
                {"kind": "concept", "id": "c_rev", "name": "revenue", "score": 0.93},
                {"kind": "metric", "id": "m_rr", "name": "Revenue Run-Rate", "score": 0.61},
            ],
            "suggestedQuery": 'SELECT "revenue"',
        },
    }})
    with pytest.raises(AnchorSqlError) as exc:
        Ontology(transport, "ws1").sql('SELECT "revenu"')
    error = exc.value
    assert error.code == "unknown_concept"
    assert error.span == (7, 15)
    assert [c["name"] for c in error.candidates] == ["revenue", "Revenue Run-Rate"]
    assert error.suggested_query == 'SELECT "revenue"'
    assert "revenue" in str(error)
    assert 'Try: SELECT "revenue"' in str(error)


def test_ontology_sql_error_carries_per_source_reasons(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/ontology/query", {"data": {
        "ok": False,
        "error": {
            "code": "no_join_path",
            "message": "No join path reaches every selected concept.",
            "perSource": [{"datasetId": "d1", "datasetName": "Shipments", "reason": "no shared identifier"}],
        },
    }})
    with pytest.raises(AnchorSqlError) as exc:
        Ontology(transport, "ws1").sql('SELECT "revenue", "shipped_at"')
    assert exc.value.per_source[0]["datasetName"] == "Shipments"
    assert "Shipments" in str(exc.value)
    assert "no shared identifier" in str(exc.value)


def test_ontology_sql_empty_frame_keeps_engine_columns(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/ontology/query", {"data": {
        "ok": True, "kind": "rows", "columns": ["revenue", "region"], "rows": [],
    }})
    frame = Ontology(transport, "ws1").sql('SELECT "revenue", "region" LIMIT 0').to_frame()
    assert list(frame.columns) == ["revenue", "region"]
    assert frame.empty


def test_ontology_sql_html_escapes_warnings(api, transport):
    payload = {"data": {**ROWS_PAGE["data"], "warnings": ["<script>alert(1)</script>"]}}
    api.on("POST", "/api/v1/workspaces/ws1/ontology/query", payload)
    rendered = Ontology(transport, "ws1").sql('SELECT "revenue"')._repr_html_()
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_removed_query_and_ask_point_at_sql(api, transport):
    ontology = Ontology(transport, "ws1")
    with pytest.raises(RootCauseError, match=r"sql\("):
        ontology.query(select=["revenue"])
    with pytest.raises(RootCauseError, match=r"sql\("):
        ontology.ask("average revenue in Florida")
    assert api.requests == []
