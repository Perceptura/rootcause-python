import json

import pytest

from rootcause.errors import RootCauseError
from rootcause.jupyter import DEFAULT_APP_URI, McpGateway


TOOLS = {
    "tools": [
        {"name": "query_causal_graph", "_meta": {"ui": {"resourceUri": "ui://widget/twin.html"}}},
        {"name": "get_workspace_overview"},
    ]
}


def test_call_unwraps_jsonrpc_result(api, transport):
    api.on("POST", "/api/v1/mcp", {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
    gateway = McpGateway(transport)
    assert gateway.call("tools/list") == {"ok": True}
    request = api.requests[-1]
    assert request.headers["mcp-protocol-version"]
    body = json.loads(request.content.decode())
    assert body["method"] == "tools/list"


def test_call_raises_on_jsonrpc_error(api, transport):
    api.on("POST", "/api/v1/mcp", {"jsonrpc": "2.0", "id": 1, "error": {"message": "no such tool"}})
    with pytest.raises(RootCauseError, match="no such tool"):
        McpGateway(transport).call_tool("nope", {})


def test_app_uri_mapping_with_fallback(api, transport):
    api.on("POST", "/api/v1/mcp", {"jsonrpc": "2.0", "id": 1, "result": TOOLS})
    gateway = McpGateway(transport)
    assert gateway.app_uri_for("query_causal_graph") == "ui://widget/twin.html"
    assert gateway.app_uri_for("get_workspace_overview") == DEFAULT_APP_URI
    assert len(api.requests) == 1


def test_read_bundle_requires_content(api, transport):
    api.on("POST", "/api/v1/mcp", {"jsonrpc": "2.0", "id": 1, "result": {"contents": []}})
    with pytest.raises(RootCauseError, match="no bundle"):
        McpGateway(transport).read_bundle("ui://widget/twin.html")


def test_read_bundle_returns_html(api, transport):
    api.on(
        "POST",
        "/api/v1/mcp",
        {"jsonrpc": "2.0", "id": 1, "result": {"contents": [{"text": "<!doctype html><html></html>"}]}},
    )
    html = McpGateway(transport).read_bundle("ui://widget/twin.html")
    assert html.startswith("<!doctype html>")
