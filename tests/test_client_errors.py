"""Every guard that fires before, or instead of, a stack trace.

One test per mistake a caller can make: the message has to name the argument
and say what to do about it, and nothing may leak an httpx, pyarrow or KeyError
traceback to the notebook.
"""

import httpx
import pandas as pd
import pytest

from rootcause import _guard, direct
from rootcause._http import Transport, expect, jsonable, poll_run, resolve_transport
from rootcause.errors import (
    AuthenticationError,
    ConnectionFailedError,
    InvalidArgumentError,
    JobTimeoutError,
    MalformedResponseError,
    MissingDependencyError,
    RootCauseError,
)
from rootcause.graph import Graph
from rootcause.ontology import Ontology
from rootcause.results import SimulationResult, SweepResult
from rootcause.twin import Twin
from rootcause.workspace import Source, Workspace

FRAME = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})


def _twin(transport, kind: str = "static") -> Twin:
    return Twin(
        transport,
        "ws1",
        {"id": "dt1", "name": "demo", "type": kind},
        {"id": "v1", "lifecycleState": "trained", "createdAt": "2026-01-01"},
    )


def _raising_transport(error: Exception) -> Transport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return Transport("https://fake.rootcause.test", "pk_test", httpx_transport=httpx.MockTransport(handler))


# --- base_url and credentials ------------------------------------------------

@pytest.mark.parametrize(
    "base_url, expected",
    [
        ("platform.rootcause.ai", "needs a scheme"),
        ("", "empty"),
        ("   ", "empty"),
        ("ftp://platform.rootcause.ai", "http:// or https://"),
    ],
)
def test_unusable_base_url_is_rejected_before_any_request(base_url, expected):
    with pytest.raises(InvalidArgumentError, match=expected):
        Transport(base_url, "pk_test")


def test_base_url_scheme_error_shows_the_fixed_url():
    with pytest.raises(InvalidArgumentError, match="https://platform.rootcause.ai"):
        Transport("platform.rootcause.ai", "pk_test")


def test_blank_api_key_says_so_rather_than_401ing_later(monkeypatch):
    monkeypatch.setenv("ROOTCAUSE_API_KEY", "   ")
    with pytest.raises(AuthenticationError, match="empty"):
        resolve_transport()


def test_headless_session_without_credentials_asks_for_a_key_instead_of_a_browser(monkeypatch):
    monkeypatch.delenv("ROOTCAUSE_API_KEY", raising=False)
    monkeypatch.setenv("CI", "1")
    monkeypatch.setattr("rootcause._http._read_credentials", dict)

    with pytest.raises(AuthenticationError) as exc:
        resolve_transport(base_url="https://fake.rootcause.test")

    assert "ROOTCAUSE_API_KEY" in str(exc.value)
    assert "browser login" in str(exc.value)


# --- connection failures -----------------------------------------------------

@pytest.mark.parametrize(
    "error, expected",
    [
        (httpx.ConnectError("nodename nor servname provided"), "Nothing is listening"),
        (httpx.ConnectTimeout("timed out"), "did not answer in time"),
        (httpx.ReadTimeout("too slow"), "raise timeout="),
        (httpx.WriteTimeout("stalled"), "upload stalled"),
    ],
)
def test_transport_failures_become_one_readable_sentence(error, expected):
    transport = _raising_transport(error)
    with pytest.raises(ConnectionFailedError) as exc:
        transport.request("POST", "/api/v1/me", json_body={})

    message = str(exc.value)
    assert expected in message
    assert "fake.rootcause.test" in message


def test_an_unresolvable_hostname_says_so_and_is_not_retried():
    import socket

    # httpx wraps httpcore, which wraps the resolver's error — as in the real thing.
    inner = httpx.ConnectError("nope")
    inner.__cause__ = socket.gaierror(-2, "Name or service not known")
    error = httpx.ConnectError("nope")
    error.__cause__ = inner
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise error

    transport = Transport("https://typo.rootcause.invalid", "pk_test", httpx_transport=httpx.MockTransport(handler))
    with pytest.raises(ConnectionFailedError, match="does not resolve"):
        transport.request("GET", "/api/v1/me")

    assert len(attempts) == 1


def test_a_transient_get_failure_is_retried(monkeypatch):
    monkeypatch.setattr("rootcause._http.time.sleep", lambda _seconds: None)
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) < 3:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json={"data": {"ok": True}})

    transport = Transport("https://fake.rootcause.test", "pk_test", httpx_transport=httpx.MockTransport(handler))
    assert transport.request("GET", "/api/v1/me") == {"data": {"ok": True}}
    assert len(attempts) == 3


def test_connection_failure_keeps_the_underlying_cause_for_debugging():
    transport = _raising_transport(httpx.ConnectError("boom"))
    with pytest.raises(ConnectionFailedError) as exc:
        transport.request("POST", "/api/v1/me", json_body={})
    assert isinstance(exc.value.__cause__, httpx.ConnectError)


def test_html_login_page_on_a_200_is_not_a_json_decode_error(api, transport):
    api.on("GET", "/api/v1/me", lambda _r: httpx.Response(200, html="<html>Sign in</html>"))
    with pytest.raises(MalformedResponseError) as exc:
        transport.request("GET", "/api/v1/me")

    message = str(exc.value)
    assert "instead of JSON" in message
    assert "base_url" in message


# --- payload encoding --------------------------------------------------------

def test_numpy_and_missing_values_survive_encoding():
    frame = pd.DataFrame({"n": [1, 2], "t": pd.to_datetime(["2026-01-01", "2026-01-02"])})
    payload = jsonable(
        {
            "int": frame["n"].max(),
            "stamp": frame["t"].iloc[0],
            "nan": float("nan"),
            "inf": float("inf"),
            "nat": pd.NaT,
            "array": frame["n"].to_numpy(),
            "nested": {"set": {1}},
        }
    )
    assert payload["int"] == 2
    assert payload["stamp"].startswith("2026-01-01")
    assert payload["nan"] is None and payload["inf"] is None and payload["nat"] is None
    assert payload["array"] == [1, 2]
    assert payload["nested"] == {"set": [1]}


def test_a_numpy_value_in_do_reaches_the_wire_as_json(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/simulations", {"data": {"runId": "r1"}})
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r1", {"data": {"status": "completed"}})

    _twin(transport).intervene({"price": FRAME["a"].max()}, outcomes=["b"])

    body = api.body_of("POST", "/simulations")
    assert body["scenario"]["interventions"][0]["valueSpec"]["value"] == 2.0


# --- job and run dispatch ----------------------------------------------------

def test_a_write_that_returns_no_job_id_names_the_verb():
    with pytest.raises(MalformedResponseError) as exc:
        expect({"data": {"status": "queued"}}, "jobId", "training job")

    message = str(exc.value)
    assert "training job" in message
    assert "no jobId" in message


def test_discover_without_a_job_id_does_not_raise_a_keyerror(api, transport):
    api.on("POST", "/api/v1/workspaces/ws1/digital-twins/dt1/versions/v1/discover", {"data": {}})
    with pytest.raises(MalformedResponseError, match="discovery job"):
        _twin(transport).discover()


def test_a_run_that_404s_briefly_is_treated_as_pending(api, transport):
    answers = iter([httpx.Response(404, json={"detail": "not yet"}), httpx.Response(200, json={"data": {"status": "completed"}})])
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r1", lambda _r: next(answers))

    assert poll_run(transport, "ws1", "r1", interval=0.0)["status"] == "completed"


def test_a_run_that_never_finishes_says_how_to_wait_longer(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r1", {"data": {"status": "running"}})
    with pytest.raises(JobTimeoutError) as exc:
        poll_run(transport, "ws1", "r1", interval=0.0, timeout=0.0)

    message = str(exc.value)
    assert "keeps running on the platform" in message
    assert "timeout=" in message


# --- frames ------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [
        ([{"a": 1}], "pd.DataFrame"),
        ({"a": [1]}, "pd.DataFrame"),
        ("data.csv", "not str"),
        (None, "not NoneType"),
    ],
)
def test_something_that_is_not_a_dataframe_says_what_it_is(value, expected):
    with pytest.raises(InvalidArgumentError, match=expected):
        _guard.frame(value)


def test_an_empty_frame_is_refused():
    with pytest.raises(InvalidArgumentError, match="no rows"):
        _guard.frame(pd.DataFrame({"a": []}))


def test_duplicate_columns_are_named():
    frame = pd.DataFrame([[1, 2]], columns=["a", "a"])
    with pytest.raises(InvalidArgumentError, match="duplicate column name.*a"):
        _guard.frame(frame)


def test_blank_column_names_are_counted():
    frame = pd.DataFrame([[1, 2]], columns=["a", " "])
    with pytest.raises(InvalidArgumentError, match="blank column name"):
        _guard.frame(frame)


def test_a_column_holding_python_objects_fails_as_an_argument_not_as_arrow():
    frame = pd.DataFrame({"a": [{1, 2}], "b": [object()]})
    with pytest.raises(InvalidArgumentError, match="could not be serialised"):
        _guard.to_parquet(frame)


@pytest.mark.parametrize(
    "blob, expected",
    [(b"", "came back empty"), (b"<html>nope</html>", "not readable parquet")],
)
def test_an_unreadable_export_is_not_an_arrow_traceback(blob, expected):
    with pytest.raises(MalformedResponseError, match=expected):
        _guard.from_parquet(blob, 'source "sales"')


def test_source_export_failure_names_the_source(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/sources/s1/export/parquet", lambda _r: httpx.Response(200, content=b"nope"))
    source = Source(transport, "ws1", {"id": "s1", "name": "sales"})
    with pytest.raises(MalformedResponseError, match='source "sales"'):
        source.to_frame()


def test_extend_rejects_a_list_of_dicts_before_uploading(api, transport):
    source = Source(transport, "ws1", {"id": "s1", "name": "sales"})
    with pytest.raises(InvalidArgumentError, match="pd.DataFrame"):
        source.extend([{"a": 1}])
    assert api.requests == []


# --- direct mode -------------------------------------------------------------

def test_discover_rejects_a_non_frame_before_touching_the_platform(api, transport):
    with pytest.raises(InvalidArgumentError, match="pd.DataFrame"):
        direct.discover([{"a": 1}], transport=transport)
    assert api.requests == []


def test_discover_checks_column_names_against_the_frame_and_suggests(api, transport):
    with pytest.raises(InvalidArgumentError) as exc:
        direct.discover(FRAME, target="aa", transport=transport)

    message = str(exc.value)
    assert 'target="aa"' in message
    assert "Did you mean: a" in message
    assert api.requests == []


def test_discover_lists_the_columns_when_nothing_is_close(api, transport):
    with pytest.raises(InvalidArgumentError, match="Columns: a, b"):
        direct.discover(FRAME, time="quarter", transport=transport)
    assert api.requests == []


@pytest.mark.parametrize("argument", ["target", "time", "entity"])
def test_every_column_argument_is_checked(argument, transport):
    with pytest.raises(InvalidArgumentError, match=f'{argument}="nope"'):
        direct.discover(FRAME, transport=transport, **{argument: "nope"})


def test_load_twin_from_a_missing_path_says_where_the_file_comes_from(transport):
    with pytest.raises(InvalidArgumentError, match="twin.save()"):
        direct.load_twin("/nope/missing.rctwin", transport=transport)


def test_load_twin_from_a_directory_is_caught(tmp_path, transport):
    with pytest.raises(InvalidArgumentError, match="directory"):
        direct.load_twin(tmp_path, transport=transport)


def test_load_twin_from_something_that_is_not_an_archive_is_caught(tmp_path, transport):
    path = tmp_path / "twin.rctwin"
    path.write_text("not a zip")
    with pytest.raises(InvalidArgumentError, match="not a .rctwin archive"):
        direct.load_twin(path, transport=transport)


# --- workspace ---------------------------------------------------------------

def _workspace(api, transport) -> Workspace:
    api.on("GET", "/api/v1/workspaces/ws1/ontology/concepts", {"data": []})
    return Workspace(transport, {"id": "ws1", "name": "demo"})


def test_upload_needs_a_name(api, transport):
    with pytest.raises(InvalidArgumentError, match="name="):
        _workspace(api, transport).upload(FRAME, "  ")
    assert api.requests == []


def test_create_twin_needs_exactly_one_data_argument(api, transport):
    workspace = _workspace(api, transport)
    with pytest.raises(InvalidArgumentError, match="not both"):
        workspace.create_twin("t", dataset_id="d1", source_id="s1")
    with pytest.raises(InvalidArgumentError, match="needs data"):
        workspace.create_twin("t")
    assert api.requests == []


def test_create_twin_rejects_an_unknown_kind_and_lists_them(api, transport):
    with pytest.raises(InvalidArgumentError) as exc:
        _workspace(api, transport).create_twin("t", kind="timeseries", source_id="s1")

    message = str(exc.value)
    assert 'kind="timeseries"' in message
    assert "multi-environment-temporal" in message


def test_a_connector_preview_that_answers_the_wrong_shape_is_caught(api, transport):
    from rootcause.workspace import Connector

    api.on("POST", "/api/v1/connectors/c1/preview-query", {"data": ["oops"]})
    connector = Connector(transport, "ws1", {"id": "c1", "name": "warehouse"})
    with pytest.raises(MalformedResponseError, match="not a result payload"):
        connector.query("SELECT 1")


# --- twin verbs --------------------------------------------------------------

@pytest.mark.parametrize(
    "call, expected",
    [
        (lambda t: t.sample(n=0), "n= must be at least 1"),
        (lambda t: t.sample(n="lots"), "whole number"),
        (lambda t: t.new_version(bump="massive"), 'bump="massive"'),
        (lambda t: t.score(pd.DataFrame(), [{"variable": "y", "value": 1}]), "no rows"),
        (lambda t: t.score([{"a": 1}], []), "targets="),
        (lambda t: t.score(["not a dict"], [{"variable": "y"}]), "dicts keyed by"),
        (lambda t: t.score([], [{"variable": "y"}]), "non-empty list"),
        (lambda t: t.sankey(), "exactly one"),
        (lambda t: t.sankey(node="a", edge=("a", "b")), "exactly one"),
        (lambda t: t.sankey(edge="a->b"), "(cause, effect) pair"),
    ],
)
def test_static_twin_arguments_are_checked_before_dispatch(api, transport, call, expected):
    with pytest.raises(InvalidArgumentError, match=re_escape(expected)):
        call(_twin(transport))
    assert api.requests == []


@pytest.mark.parametrize(
    "call, expected",
    [
        (lambda t: t.forecast(0), "horizon= must be at least 1"),
        (lambda t: t.forecast(4, confidence=1.5), "between 0 and 1"),
        (lambda t: t.forecast(4, confidence="high"), "between 0 and 1"),
    ],
)
def test_forecast_arguments_are_checked_before_dispatch(api, transport, call, expected):
    with pytest.raises(InvalidArgumentError, match=re_escape(expected)):
        call(_twin(transport, "temporal"))
    assert api.requests == []


def test_forecast_rejects_an_unknown_aggregate_and_lists_them(api, transport):
    with pytest.raises(InvalidArgumentError) as exc:
        _twin(transport, "multi-environment-temporal").forecast(4, aggregate="median")

    assert 'aggregate="median"' in str(exc.value)
    assert "avg, max, min, sum" in str(exc.value)
    assert api.requests == []


def test_save_into_a_missing_directory_is_caught_before_the_export(api, transport):
    with pytest.raises(InvalidArgumentError, match="No directory"):
        _twin(transport).save("/nope/nowhere/twin.rctwin")
    assert api.requests == []


def test_a_question_the_translator_cannot_use_explains_what_to_state(api, transport):
    api.on(
        "POST",
        "/api/v1/workspaces/ws1/digital-twins/dt1/versions/v1/scenario-from-query",
        {"data": {"message": "please be more specific"}},
    )
    with pytest.raises(RootCauseError) as exc:
        _twin(transport).ask("what about stuff")

    message = str(exc.value)
    assert "Name the variables to change" in message
    assert "please be more specific" in message


# --- graph -------------------------------------------------------------------

def _graph(api, transport, payload) -> Graph:
    api.on("GET", "/api/v1/workspaces/ws1/digital-twins/dt1/versions/v1/graph", {"data": payload})
    return Graph(_twin(transport))


def test_an_undiscovered_graph_says_to_run_discovery(api, transport):
    graph = _graph(api, transport, {})
    with pytest.raises(RootCauseError) as exc:
        _ = graph.edges

    message = str(exc.value)
    assert "no causal graph" in message
    assert "twin.discover()" in message


def test_an_undiscovered_graph_still_reprs(api, transport):
    graph = _graph(api, transport, {})
    assert "not discovered" in repr(graph)
    assert "no causal graph" in graph._repr_html_()


def test_adjacency_rejects_an_unknown_cell_value_even_with_no_edges(api, transport):
    graph = _graph(api, transport, {"nodes": [{"name": "a"}], "relationships": []})
    with pytest.raises(InvalidArgumentError, match='values="middling"'):
        graph.adjacency(values="middling")


def test_to_networkx_without_networkx_names_the_extra(api, transport, monkeypatch):
    graph = _graph(api, transport, {"nodes": [{"name": "a"}], "relationships": []})
    monkeypatch.setattr(_guard, "require", _refusing_import("networkx"))

    with pytest.raises(MissingDependencyError) as exc:
        graph.to_networkx()
    assert 'rootcause-sdk[graph]' in str(exc.value)


def test_a_missing_extra_names_the_extra_that_installs_it(monkeypatch):
    monkeypatch.setattr(_guard, "_EXTRAS", {"nowhere": "jupyter"})
    with pytest.raises(MissingDependencyError, match=r"rootcause-sdk\[jupyter\]"):
        _guard.require("nowhere")


def test_a_missing_plain_dependency_says_pip_install():
    with pytest.raises(MissingDependencyError, match="pip install nowhere"):
        _guard.require("nowhere")


# --- results -----------------------------------------------------------------

def _result(transport, results) -> SimulationResult:
    result = SimulationResult(transport, "ws1", "r1", {"status": "completed"})
    result._results = results
    return result


def test_a_result_with_nothing_tabular_points_at_the_raw_payload(transport):
    with pytest.raises(InvalidArgumentError, match=".results"):
        _result(transport, {"summary": "all good"}).to_frame()


def test_a_bad_table_path_lists_the_real_ones(transport):
    result = _result(transport, {"outer": {"rows": [{"a": 1}]}})
    with pytest.raises(InvalidArgumentError, match="outer.rows"):
        result.to_frame(path="outer.wrong")


def test_a_run_with_no_sweep_explains_how_sweeps_are_made(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r1/sweep", {"data": {"metrics": []}})
    with pytest.raises(RootCauseError, match="rc.range"):
        _result(transport, {}).sweep()


def test_a_multi_metric_sweep_names_the_metrics(api, transport):
    api.on("GET", "/api/v1/workspaces/ws1/simulations/r1/sweep", {"data": {"metrics": ["a", "b"]}})
    with pytest.raises(RootCauseError, match="metric= one of: a, b"):
        _result(transport, {}).sweep()


def test_sweep_result_does_not_recurse_on_a_private_attribute():
    sweep = SweepResult.__new__(SweepResult)
    with pytest.raises(AttributeError):
        _ = sweep._frame


# --- interventions -----------------------------------------------------------

@pytest.mark.parametrize(
    "call, expected",
    [
        (lambda rc: rc.prob("yes", 1.4), "between 0 and 1"),
        (lambda rc: rc.prob("yes"), "needs a probability"),
        (lambda rc: rc.prob({"yes": 0.5, "no": 0.5}), "exactly one"),
        (lambda rc: rc.pct("loads"), "takes a number"),
        (lambda rc: rc.add(None), "takes a number, not NoneType"),
        (lambda rc: rc.range(30, 15), "from_ < to"),
        (lambda rc: rc.range(1, 5, steps=1), "at least 2 steps"),
        (lambda rc: rc.metric("", "SELECT 1 AS value FROM df"), "needs a name"),
        (lambda rc: rc.metric("m", "AVG(revenue)"), "must be a SELECT"),
        (lambda rc: rc.compile_do({}), "non-empty dict"),
        (lambda rc: rc.compile_where("region = EMEA"), "not str"),
        (lambda rc: rc.compile_where({"a": ("~=", 1)}), "(operator, value)"),
    ],
)
def test_intervention_builders_refuse_nonsense(call, expected):
    from rootcause import interventions

    with pytest.raises(InvalidArgumentError, match=re_escape(expected)):
        call(interventions)


def test_intervention_errors_are_still_value_errors_for_existing_handlers():
    from rootcause import interventions

    with pytest.raises(ValueError):
        interventions.prob("yes", 2.0)


# --- ontology ----------------------------------------------------------------

def _ontology(api, transport, concepts=()) -> Ontology:
    api.on("GET", "/api/v1/workspaces/ws1/ontology/concepts", {"data": list(concepts)})
    return Ontology(transport, "ws1")


def test_an_empty_query_is_refused(api, transport):
    with pytest.raises(InvalidArgumentError, match="select="):
        _ontology(api, transport).query()
    assert api.requests == []


def test_an_unknown_filter_operator_lists_the_real_ones(api, transport):
    ontology = _ontology(api, transport, [{"id": "c1", "name": "Revenue"}])
    with pytest.raises(InvalidArgumentError, match="Unknown operator"):
        ontology.query(select=["Revenue"], where=[("Revenue", "approximately", 5)])


def test_a_malformed_filter_tuple_says_the_shape(api, transport):
    ontology = _ontology(api, transport, [{"id": "c1", "name": "Revenue"}])
    with pytest.raises(InvalidArgumentError, match="triples"):
        ontology.query(select=["Revenue"], where=[("Revenue", 5)])


def test_an_empty_prompt_is_refused(api, transport):
    with pytest.raises(InvalidArgumentError, match="prompt="):
        _ontology(api, transport).ask("   ")


# --- notebook apps -----------------------------------------------------------

def test_a_tool_that_answers_is_error_raises_instead_of_mounting(api, transport):
    from rootcause import jupyter

    api.on(
        "POST",
        "/api/v1/mcp",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"isError": True, "content": [{"type": "text", "text": "twin is not trained"}]},
        },
    )
    with pytest.raises(RootCauseError, match="twin is not trained"):
        jupyter.app("query_causal_graph", {"workspaceId": "ws1"}, transport=transport)


# --- session -----------------------------------------------------------------

def test_a_failed_relogin_leaves_the_working_session_open(monkeypatch, transport):
    import rootcause as rc

    monkeypatch.setitem(rc._session, "transport", transport)
    monkeypatch.setattr(
        "rootcause.resolve_transport",
        lambda **_kwargs: (_ for _ in ()).throw(AuthenticationError("nope")),
    )

    with pytest.raises(AuthenticationError):
        rc.login(api_key="bad")

    assert rc._session["transport"] is transport
    assert not transport._client.is_closed


def _refusing_import(module: str):
    def refuse(name: str):
        if name == module:
            raise MissingDependencyError(f'This needs the {name} package: pip install "rootcause-sdk[graph]"')
        return __import__(name)

    return refuse


def re_escape(text: str) -> str:
    import re

    return re.escape(text)
