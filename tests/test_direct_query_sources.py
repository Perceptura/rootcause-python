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


def test_a_source_the_platform_did_not_describe_is_unknown_rather_than_guessed(transport):
    """Direct query predates these fields, and the REST route that creates one predates them too,
    so a server that does not send readMode can still hold sources of either kind. Calling those
    snapshots would be a guess that is wrong exactly where a caller would act on it."""
    legacy = Source(transport, WS, {"id": "src3", "name": "legacy"})

    assert legacy.read_mode == "unknown"
    assert legacy.direct_query is None


def test_a_source_just_created_is_not_mislabelled_by_a_platform_that_cannot_describe_it(api, transport):
    """The failure this guards: /connectors/{id}/direct-query has been on the platform for a
    while, but the source GET only learned to report readMode later. Between those two, creating
    a federated source and reading it straight back said "snapshot" about a source this very call
    had just asked to be federated."""
    api.on("POST", "/api/v1/connectors/conn1/direct-query", {"data": {"sourceId": "src1"}}, status=201)
    api.on("GET", f"/api/v1/workspaces/{WS}/sources/src1", {"data": {"id": "src1", "name": "readings"}})

    source = _connector(transport).direct_query_table(
        "readings_1h", ordering_column="ts", statement_timeout_seconds=30,
    )

    assert source.read_mode == "direct_query"
    assert source.direct_query == {
        "orderingColumn": "ts",
        "appendOnly": False,
        "statementTimeoutSeconds": 30,
        "maxRowsScanned": None,
    }


def test_what_the_platform_does_say_wins_over_what_this_call_asked_for(api, transport):
    """Creation can settle an ordering column the caller left to it, so the server's answer is
    the authority wherever it gives one."""
    api.on("POST", "/api/v1/connectors/conn1/direct-query", {"data": {"sourceId": "src1"}}, status=201)
    api.on("GET", f"/api/v1/workspaces/{WS}/sources/src1", {"data": FEDERATED_DOC})

    source = _connector(transport).direct_query_table("readings_1h", ordering_column="ts")

    assert source.direct_query == FEDERATED_DOC["directQuery"]


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
    assert source.dropped_columns == [{"field": "blob", "type": "VARIANT"}]


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


def test_every_direct_query_setting_reaches_the_request_body(api, transport):
    api.on("POST", "/api/v1/connectors/conn1/direct-query", {"data": {"sourceId": "src1"}}, status=201)
    api.on("GET", f"/api/v1/workspaces/{WS}/sources/src1", {"data": FEDERATED_DOC})

    _connector(transport).direct_query_table(
        "readings_1h",
        ordering_column="ts",
        append_only=True,
        statement_timeout_seconds=30,
        max_rows_scanned=1_000_000,
        relation="daq.readings_1h",
        parent_id="folder1",
    )

    body = api.body_of("POST", "/direct-query")
    assert body["appendOnly"] is True
    assert body["statementTimeoutSeconds"] == 30
    assert body["maxRowsScanned"] == 1_000_000
    assert body["relation"] == "daq.readings_1h"
    assert body["parentId"] == "folder1"
    assert body["config"] == {"table": "readings_1h"}


def test_a_misspelt_setting_is_refused_rather_than_sent_as_a_connector_override(transport):
    """The failure that has no symptom: a setting that lands inside `config` is accepted by the
    route, ignored by the backend, and the source comes back with no cap and no complaint."""
    with pytest.raises(TypeError):
        _connector(transport).direct_query_table(
            "readings_1h", ordering_column="ts", statement_timeout=30,
        )

    with pytest.raises(TypeError):
        _connector(transport).direct_query_table(
            "readings_1h", ordering_column="ts", statementTimeoutSeconds=30,
        )


def test_an_omitted_setting_is_left_out_of_the_body_rather_than_sent_as_null(api, transport):
    api.on("POST", "/api/v1/connectors/conn1/direct-query", {"data": {"sourceId": "src1"}}, status=201)
    api.on("GET", f"/api/v1/workspaces/{WS}/sources/src1", {"data": FEDERATED_DOC})

    _connector(transport).direct_query_table("readings_1h", ordering_column="ts")

    body = api.body_of("POST", "/direct-query")
    assert "statementTimeoutSeconds" not in body
    assert "maxRowsScanned" not in body
    assert "relation" not in body
    assert "parentId" not in body


def test_a_source_with_no_dropped_columns_answers_with_an_empty_list(transport):
    assert Source(transport, WS, dict(SNAPSHOT_DOC)).dropped_columns == []
