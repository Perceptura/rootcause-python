"""Interactive RootCause apps under notebook cells.

The platform ships every MCP tool's result with an interactive App bundle
(what Claude and ChatGPT render inline). This module is a notebook host for
those same bundles: the bundle runs in a sandboxed iframe, speaks its usual
postMessage JSON-RPC, and this host proxies its tools/call round-trips to the
platform's MCP gateway over HTTP with the session's credentials. Nothing is
re-implemented per widget; whatever the platform can render, the notebook can.

    import rootcause as rc
    from rootcause.jupyter import app

    rc.login()
    app("query_causal_graph", {"workspaceId": ws.id, "digitalTwinId": twin.id})

Requires the jupyter extra: pip install "rootcause-sdk[jupyter]".
"""

import json
from typing import Any

from rootcause._http import Transport
from rootcause.errors import RootCauseError

MCP_PROTOCOL_VERSION = "2025-11-25"
DEFAULT_APP_URI = "ui://widget/widgets.html"

_HOST_ESM = """
export function render({ model, el }) {
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-scripts");
  frame.style.width = "100%";
  frame.style.border = "0";
  frame.style.background = "transparent";
  frame.style.height = (model.get("height") || 480) + "px";
  el.appendChild(frame);

  const send = (msg) => frame.contentWindow.postMessage(msg, "*");
  const reply = (id, result) => send({ jsonrpc: "2.0", id, result });
  const notify = (method, params) => send({ jsonrpc: "2.0", method, params });

  const theme = model.get("theme") ||
    (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

  const pending = new Map();
  let counter = 0;

  const onCustom = (msg) => {
    if (msg && msg.kind === "tools/call:result" && pending.has(msg.callId)) {
      const frameId = pending.get(msg.callId);
      pending.delete(msg.callId);
      reply(frameId, msg.result);
    }
  };
  model.on("msg:custom", onCustom);

  const onMessage = (event) => {
    if (event.source !== frame.contentWindow) return;
    const msg = event.data;
    if (!msg || msg.jsonrpc !== "2.0") return;

    if (msg.method === "ui/initialize") {
      reply(msg.id, {
        protocolVersion: (msg.params && msg.params.protocolVersion) || "2025-11-21",
        hostInfo: { name: "rootcause-sdk-jupyter", version: model.get("sdk_version") || "0.0.0" },
        hostCapabilities: { openLink: {} },
        hostContext: {
          theme,
          toolInfo: {
            tool: { name: model.get("tool_name"), inputSchema: { type: "object", properties: {} } },
          },
          containerDimensions: { width: el.clientWidth || 900, height: model.get("height") || 480 },
          displayMode: "inline",
        },
      });
      return;
    }

    if (msg.method === "ui/notifications/initialized") {
      notify("ui/notifications/tool-input", { arguments: JSON.parse(model.get("tool_arguments") || "{}") });
      notify("ui/notifications/tool-result", JSON.parse(model.get("tool_result") || "{}"));
      return;
    }

    if (msg.method === "tools/call") {
      const callId = "call-" + ++counter;
      pending.set(callId, msg.id);
      model.send({ kind: "tools/call", callId, params: msg.params });
      return;
    }

    if (msg.method === "ui/notifications/size-changed") {
      const height = Number(msg.params && msg.params.height);
      if (Number.isFinite(height) && height > 0) frame.style.height = Math.ceil(height) + "px";
      return;
    }

    if (msg.method === "ui/open-link") {
      const url = msg.params && msg.params.url;
      if (typeof url === "string" && /^https?:/.test(url)) window.open(url, "_blank", "noopener");
      reply(msg.id, {});
      return;
    }

    if (msg.id !== undefined) reply(msg.id, {});
  };

  window.addEventListener("message", onMessage);
  frame.srcdoc = model.get("bundle_html");

  return () => {
    window.removeEventListener("message", onMessage);
    model.off("msg:custom", onCustom);
  };
}
"""


class McpGateway:
    """Stateless JSON-RPC over HTTP against the platform's MCP endpoint."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self._tool_apps: dict[str, str] | None = None

    def call(self, method: str, params: Any = None) -> Any:
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            body["params"] = params
        envelope = self._transport.request(
            "POST",
            "/api/v1/mcp",
            json_body=body,
            headers={"MCP-Protocol-Version": MCP_PROTOCOL_VERSION},
        )
        if isinstance(envelope, dict) and envelope.get("error"):
            error = envelope["error"]
            raise RootCauseError(f"MCP {method} failed: {error.get('message', error)}")
        return envelope.get("result", envelope)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return self.call("tools/call", {"name": name, "arguments": arguments})

    def app_uri_for(self, tool_name: str) -> str:
        if self._tool_apps is None:
            listing = self.call("tools/list")
            self._tool_apps = {}
            for tool in listing.get("tools", []):
                uri = ((tool.get("_meta") or {}).get("ui") or {}).get("resourceUri")
                if uri:
                    self._tool_apps[tool["name"]] = uri
        return self._tool_apps.get(tool_name, DEFAULT_APP_URI)

    def read_bundle(self, uri: str) -> str:
        result = self.call("resources/read", {"uri": uri})
        contents = result.get("contents", [])
        if not contents or not contents[0].get("text"):
            raise RootCauseError(
                f"The platform returned no bundle for {uri}; was it deployed without built MCP apps?"
            )
        return str(contents[0]["text"])


def _widget_class():
    try:
        import anywidget
        import traitlets
    except ImportError as e:
        raise RootCauseError(
            'Interactive apps need the jupyter extra: pip install "rootcause-sdk[jupyter]"'
        ) from e

    class RootCauseApp(anywidget.AnyWidget):
        _esm = _HOST_ESM
        bundle_html = traitlets.Unicode("").tag(sync=True)
        tool_name = traitlets.Unicode("").tag(sync=True)
        tool_arguments = traitlets.Unicode("{}").tag(sync=True)
        tool_result = traitlets.Unicode("{}").tag(sync=True)
        theme = traitlets.Unicode("").tag(sync=True)
        height = traitlets.Int(480).tag(sync=True)
        sdk_version = traitlets.Unicode("").tag(sync=True)

        def __init__(self, gateway: McpGateway, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._gateway = gateway
            self.on_msg(self._on_custom)

        def _on_custom(self, _widget: Any, content: Any, _buffers: Any) -> None:
            if not isinstance(content, dict) or content.get("kind") != "tools/call":
                return
            params = content.get("params") or {}
            arguments = dict(params.get("arguments") or {})
            original = json.loads(self.tool_arguments or "{}")
            if "workspaceId" not in arguments and original.get("workspaceId"):
                arguments["workspaceId"] = original["workspaceId"]
            try:
                result = self._gateway.call_tool(str(params.get("name", "")), arguments)
            except RootCauseError as e:
                result = {"isError": True, "content": [{"type": "text", "text": str(e)}]}
            self.send({"kind": "tools/call:result", "callId": content.get("callId"), "result": result})

    return RootCauseApp


def app(
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    theme: str = "",
    height: int = 480,
    transport: Transport | None = None,
    result: dict[str, Any] | None = None,
) -> Any:
    """Run an MCP tool and render its interactive app under the cell.

    The tool executes server-side with the session's credentials; its App
    bundle renders the result and any controls it carries (re-run scenario,
    expand table, approve graph change) round-trip live through the gateway.

    Args:
        tool: MCP tool name, for example `query_causal_graph`.
        arguments: The tool's arguments.
        theme: `light`, `dark`, or empty to follow the notebook.
        height: Height of the mounted app, in pixels.
        transport: Use a specific session instead of the module-level one.
        result: A pre-computed tool result to render instead of executing the
            tool — `{"content": [...], "structuredContent": {...}}`. The app's
            own controls still round-trip live through the gateway.

    Returns:
        The widget, ready for a notebook cell to display. Requires the
        `jupyter` extra.
    """
    import rootcause as rc

    resolved = transport or rc._transport()
    gateway = McpGateway(resolved)

    if result is None:
        result = gateway.call_tool(tool, arguments or {})
    bundle = gateway.read_bundle(gateway.app_uri_for(tool))

    widget_cls = _widget_class()
    return widget_cls(
        gateway,
        bundle_html=bundle,
        tool_name=tool,
        tool_arguments=json.dumps(arguments or {}),
        tool_result=json.dumps(result),
        theme=theme,
        height=height,
        sdk_version=rc.__version__,
    )
