"""The typed Jupyter app verbs must compile the exact MCP tool call their app expects."""

import pytest

import rootcause.jupyter
from rootcause.twin import Twin

WS = "ws1"
TWIN_DOC = {"id": "tw1", "name": "Churn", "type": "static"}
VERSION = {"id": "v1", "version": "1.0.0", "lifecycleState": "trained"}


@pytest.fixture
def calls(monkeypatch):
    captured = []

    def fake_app(tool, arguments=None, *, theme="", height=480, transport=None):
        captured.append({"tool": tool, "arguments": arguments, "theme": theme, "height": height, "transport": transport})
        return "widget"

    monkeypatch.setattr(rootcause.jupyter, "app", fake_app)
    return captured


def _twin(transport) -> Twin:
    twin = Twin(transport, WS, dict(TWIN_DOC))
    twin._version_doc = dict(VERSION)
    return twin


def test_console_calls_query_causal_graph(transport, calls):
    assert _twin(transport).console(height=600) == "widget"
    call = calls[-1]
    assert call["tool"] == "query_causal_graph"
    assert call["arguments"] == {"workspaceId": WS, "digitalTwinVersionId": "v1", "queryType": "graph"}
    assert call["height"] == 600
    assert call["transport"] is transport


def test_sankey_around_a_node(transport, calls):
    _twin(transport).sankey("churn", depth=3)
    call = calls[-1]
    assert call["tool"] == "analyze_digital_twin_path"
    assert call["arguments"] == {
        "workspaceId": WS,
        "digitalTwinVersionId": "v1",
        "depthLimit": 3,
        "node": "churn",
    }


def test_sankey_through_an_edge(transport, calls):
    _twin(transport).sankey(edge=("tenure", "churn"))
    assert calls[-1]["arguments"]["edge"] == {"source": "tenure", "target": "churn"}
    assert "node" not in calls[-1]["arguments"]


def test_sankey_requires_exactly_one_of_node_or_edge(transport, calls):
    twin = _twin(transport)
    with pytest.raises(ValueError, match="exactly one"):
        twin.sankey()
    with pytest.raises(ValueError, match="exactly one"):
        twin.sankey("churn", edge=("a", "b"))
    assert calls == []


def test_review_calls_review_digital_twin(transport, calls):
    _twin(transport).review()
    call = calls[-1]
    assert call["tool"] == "review_digital_twin"
    assert call["arguments"] == {"workspaceId": WS, "digitalTwinVersionId": "v1"}


def test_studio_passes_the_question_and_only_the_given_pins(transport, calls):
    _twin(transport).studio("What happens to churn if tenure rises 10%?")
    assert calls[-1]["tool"] == "query_digital_twin"
    assert calls[-1]["arguments"] == {
        "workspaceId": WS,
        "digitalTwinVersionId": "v1",
        "query": "What happens to churn if tenure rises 10%?",
    }

    _twin(transport).studio(
        "Total revenue next year?",
        targets=["revenue"],
        horizon=12,
        environments=["berlin"],
        aggregate="sum",
    )
    assert calls[-1]["arguments"] == {
        "workspaceId": WS,
        "digitalTwinVersionId": "v1",
        "query": "Total revenue next year?",
        "targetVars": ["revenue"],
        "forecastH": 12,
        "environments": ["berlin"],
        "aggregateMode": "sum",
    }
