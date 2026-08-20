"""Every handle links to its own page, with the run link landing on the run itself."""

import pytest

from rootcause.errors import RootCauseError
from rootcause.results import ScoreResult, SimulationResult
from rootcause.twin import Twin
from rootcause.workspace import DataView, Source, Workspace

WS = "ws1"


@pytest.fixture(autouse=True)
def me(api):
    api.on("GET", "/api/v1/me", {"data": {"userId": "u1", "organisationId": "org-9"}})


def test_workspace_link_is_the_space_home(transport):
    ws = Workspace(transport, {"id": WS, "name": "Demo"})
    assert ws.link() == f"{transport.base_url}/org-9/space/{WS}"


def test_org_id_is_fetched_once_then_cached(api, transport):
    ws = Workspace(transport, {"id": WS, "name": "Demo"})
    ws.link()
    ws.link()
    assert sum(1 for r in api.requests if r.url.path == "/api/v1/me") == 1


def test_twin_link_carries_the_version_label(transport):
    twin = Twin(transport, WS, {"id": "tw1", "name": "Churn", "type": "static"})
    twin._version_doc = {"id": "v1", "version": "1.0.2"}
    assert twin.link() == f"{transport.base_url}/org-9/space/{WS}/twins/tw1?version=1.0.2"


def test_graph_and_env_subset_link_to_their_twin(transport):
    twin = Twin(transport, WS, {"id": "tw1", "name": "Panel", "type": "multi-environment-temporal"})
    twin._version_doc = {"id": "v1", "version": "1.0.0"}
    assert twin.graph.link() == twin.link()
    assert twin.env("berlin").link() == twin.link()


def test_source_and_dataset_links(transport):
    assert Source(transport, WS, {"id": "src1"}).link().endswith(f"/space/{WS}/sources/src1")
    assert DataView(transport, WS, {"id": "dv1"}).link().endswith(f"/space/{WS}/datasets/dv1")


def test_ontology_link(transport):
    ws = Workspace(transport, {"id": WS, "name": "Demo"})
    assert ws.ontology.link().endswith(f"/space/{WS}/ontology")


def test_run_link_opens_the_simulate_tab_on_the_run(transport):
    result = SimulationResult(transport, WS, "run-1", {"status": "completed", "digitalTwinId": "tw1"})
    assert result.link().endswith(f"/space/{WS}/twins/tw1?tab=simulate&simulation=run-1")


def test_run_link_refetches_when_the_doc_lacks_the_twin(api, transport):
    api.on("GET", f"/api/v1/workspaces/{WS}/simulations/run-2", {"data": {"id": "run-2", "digitalTwinId": "tw9"}})
    result = SimulationResult(transport, WS, "run-2", {"status": "completed"})
    assert result.link().endswith("/twins/tw9?tab=simulate&simulation=run-2")


def test_run_link_refuses_rather_than_guessing(api, transport):
    api.on("GET", f"/api/v1/workspaces/{WS}/simulations/run-3", {"data": {"id": "run-3"}})
    result = SimulationResult(transport, WS, "run-3", {"status": "completed"})
    with pytest.raises(RootCauseError, match="does not name its twin"):
        result.link()


def test_score_link_resolves_through_the_run_doc(api, transport):
    api.on("GET", f"/api/v1/workspaces/{WS}/simulations/run-4", {"data": {"id": "run-4", "digitalTwinId": "tw2"}})
    score = ScoreResult(transport, WS, "run-4")
    assert score.link().endswith("/twins/tw2?tab=simulate&simulation=run-4")


def test_links_render_clickable_in_notebooks(transport):
    link = Workspace(transport, {"id": WS, "name": "Demo"}).link()
    assert repr(link) == str(link)
    assert link._repr_html_().startswith('<a href="')
