"""Direct query was reachable only from the UI, and a source never said which kind it was.

A snapshot and a directly-queried source differ in freshness and in what a scan costs, so the
choice between them is not cosmetic — and until this, an SDK caller could neither make one nor
tell which it had.
"""

import pytest

from rootcause.errors import RootCauseError
from rootcause.workspace import Connector, Source

WS = "ws1"
CONNECTOR = {"id": "conn1", "name": "daq", "type": "ClickHouse"}

FEDERATED_DOC = {
    "id": "src1",
    "name": "readings",
    "readMode": "direct_query",
    "directQuery": {
        "orderingColumn": "ts",
        "relation": "daq.readings_1h",
        "appendOnly": True,
        "statementTimeoutSeconds": 30,
        "maxRowsScanned": None,
    },
}

SNAPSHOT_DOC = {"id": "src2", "name": "orders", "readMode": "snapshot", "directQuery": None}


def _connector(transport) -> Connector:
    return Connector(transport, WS, dict(CONNECTOR))


def test_a_source_says_it_is_read_live_and_what_it_is_paged_by(transport):
    source = Source(transport, WS, dict(FEDERATED_DOC))

    assert source.read_mode == "direct_query"
    assert source.direct_query is not None
    assert source.direct_query["orderingColumn"] == "ts"
    assert source.direct_query["statementTimeoutSeconds"] == 30


def test_an_imported_source_is_a_snapshot_with_no_direct_query_settings(transport):
    source = Source(transport, WS, dict(SNAPSHOT_DOC))

    assert source.read_mode == "snapshot"
    assert source.direct_query is None


def test_a_source_from_an_older_platform_reads_as_a_snapshot_rather_than_unknown(transport):
    assert Source(transport, WS, {"id": "src3", "name": "legacy"}).read_mode == "snapshot"


def test_direct_query_table_creates_the_source_and_hands_it_back_queryable(api, transport):
    api.on("POST", "/api/v1/connectors/conn1/direct-query", {"data": {
        "sourceId": "src1", "workspaceId": WS, "name": "readings", "droppedColumns": [],
    }}, status=201)
    api.on("GET", f"/api/v1/workspaces/{WS}/sources/src1", {"data": FEDERATED_DOC})

    source = _connector(transport).direct_query_table(
        "readings_1h", ordering_column="ts", name="readings", database="daq",
    )

    assert isinstance(source, Source)
    assert source.id == "src1"
    assert source.read_mode == "direct_query"

    body = api.body_of("POST", "/direct-query")
    assert body["config"] == {"table": "readings_1h", "database": "daq"}
    assert body["orderingColumn"] == "ts"
    assert body["datasetName"] == "readings"
    assert body["workspaceId"] == WS


def test_the_direct_query_settings_do_not_leak_into_the_connector_selection(api, transport):
    api.on("POST", "/api/v1/connectors/conn1/direct-query", {"data": {"sourceId": "src1"}}, status=201)
    api.on("GET", f"/api/v1/workspaces/{WS}/sources/src1", {"data": FEDERATED_DOC})

    _connector(transport).direct_query_table(
        "readings_1h",
        ordering_column="ts",
        database="daq",
        append_only=True,
        statement_timeout_seconds=30,
    )

    body = api.body_of("POST", "/direct-query")
    assert body["config"] == {"table": "readings_1h", "database": "daq"}
    assert body["appendOnly"] is True
    assert body["statementTimeoutSeconds"] == 30


def test_a_storage_source_is_pointed_at_a_path_through_the_raw_verb(api, transport):
    api.on("POST", "/api/v1/connectors/conn1/direct-query", {"data": {
        "sourceId": "src1", "droppedColumns": [{"field": "blob", "type": "VARIANT"}],
    }}, status=201)
    api.on("GET", f"/api/v1/workspaces/{WS}/sources/src1", {"data": FEDERATED_DOC})

    source = _connector(transport).create_direct_query_source(
        {"path": "lake/readings"}, ordering_column="ts", name="readings",
    )

    assert api.body_of("POST", "/direct-query")["config"] == {"path": "lake/readings"}
    assert source.doc["droppedColumns"] == [{"field": "blob", "type": "VARIANT"}]


def test_a_connector_that_cannot_be_queried_directly_says_so(api, transport):
    api.on("POST", "/api/v1/connectors/conn1/direct-query", {
        "title": "Bad Request",
        "status": 400,
        "detail": "MongoDB cannot be queried directly. Import it instead.",
    }, status=400)

    with pytest.raises(RootCauseError) as raised:
        _connector(transport).direct_query_table("events", ordering_column="ts")

    assert "cannot be queried directly" in str(raised.value)


def test_a_response_with_no_source_id_is_not_reported_as_success(api, transport):
    api.on("POST", "/api/v1/connectors/conn1/direct-query", {"data": {"workspaceId": WS}}, status=201)

    with pytest.raises(RootCauseError):
        _connector(transport).direct_query_table("readings_1h", ordering_column="ts")
