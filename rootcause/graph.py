"""The causal graph handle: inspect structure, pin domain knowledge, train a twin."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

    from rootcause.twin import Twin


class Graph:
    """The causal graph of a twin version: edges, adjacency, and domain-knowledge pins."""

    def __init__(self, twin: "Twin") -> None:
        self._twin = twin
        self._payload: dict[str, Any] | None = None

    def _graph(self) -> dict[str, Any]:
        if self._payload is None:
            envelope = self._twin._transport.request("GET", f"{self._twin._version_path()}/graph")
            self._payload = envelope.get("data", envelope)
        return self._payload

    def refresh(self) -> "Graph":
        self._payload = None
        return self

    @property
    def nodes(self) -> list[str]:
        payload = self._graph()
        names = [node.get("name") for node in payload.get("nodes", []) if isinstance(node, dict)]
        if names:
            return [str(name) for name in names if name]
        edges = payload.get("relationships", [])
        return sorted({str(edge[key]) for edge in edges for key in ("source", "target") if edge.get(key)})

    @property
    def edges(self) -> "pd.DataFrame":
        import pandas as pd

        payload = self._graph()
        fixed = {
            (edge.get("source"), edge.get("target"))
            for edge in (payload.get("fixedSubGraph") or {}).get("relationships", [])
        }
        rows = [
            {
                "cause": edge.get("source"),
                "effect": edge.get("target"),
                "strength": edge.get("strength"),
                "fixed": (edge.get("source"), edge.get("target")) in fixed,
            }
            for edge in payload.get("relationships", [])
        ]
        return pd.DataFrame(rows, columns=["cause", "effect", "strength", "fixed"])

    def adjacency(self, values: str = "strength") -> "pd.DataFrame":
        """Adjacency matrix as a labelled DataFrame.

        Args:
            values: What each cell holds: `strength`, `sign`, or `bool`.

        Returns:
            A square DataFrame indexed by cause and labelled by effect.
        """
        import pandas as pd

        nodes = self.nodes
        matrix = pd.DataFrame(0.0, index=nodes, columns=nodes)
        for edge in self._graph().get("relationships", []):
            source, target = edge.get("source"), edge.get("target")
            if source not in matrix.index or target not in matrix.columns:
                continue
            strength = edge.get("strength")
            strength = 1.0 if strength is None else float(strength)
            if values == "strength":
                matrix.loc[source, target] = strength
            elif values == "sign":
                matrix.loc[source, target] = 1.0 if strength >= 0 else -1.0
            elif values == "bool":
                matrix.loc[source, target] = 1.0
            else:
                raise ValueError('values must be "strength", "sign", or "bool"')
        if values == "bool":
            return matrix.astype(bool)
        return matrix

    def to_numpy(self, values: str = "strength"):
        return self.adjacency(values=values).to_numpy()

    def to_networkx(self):
        import networkx as nx

        graph = nx.DiGraph()
        graph.add_nodes_from(self.nodes)
        for edge in self._graph().get("relationships", []):
            graph.add_edge(edge.get("source"), edge.get("target"), strength=edge.get("strength"))
        return graph

    def pin(self, cause: str, effect: str) -> "Graph":
        """Fix an edge as present: domain knowledge the next discovery run must honour.

        Args:
            cause: The causing variable.
            effect: The affected variable.

        Returns:
            This graph, refreshed.
        """
        self._twin._transport.request(
            "PATCH",
            f"{self._twin._version_path()}/graph/fixed",
            json_body={"addEdges": [{"source": cause, "target": effect}]},
        )
        return self.refresh()

    def forbid(self, cause: str, effect: str) -> "Graph":
        """Fix an edge as absent (anti-edge).

        Args:
            cause: The causing variable.
            effect: The affected variable.

        Returns:
            This graph, refreshed.
        """
        self._twin._transport.request(
            "PATCH",
            f"{self._twin._version_path()}/graph/fixed",
            json_body={"removeEdges": [{"source": cause, "target": effect}]},
        )
        return self.refresh()

    def train(self, *, timeout: float = 7200.0) -> "Twin":
        return self._twin.train(timeout=timeout)

    def __repr__(self) -> str:
        payload = self._graph()
        return f"Graph(nodes={len(self.nodes)}, edges={len(payload.get('relationships', []))})"

    def _repr_html_(self) -> str:
        edges = self.edges
        header = f"<p><b>Causal graph</b> — {len(self.nodes)} nodes, {len(edges)} edges</p>"
        return f"<div>{header}{edges.head(25)._repr_html_()}</div>"
