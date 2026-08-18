"""The workspace semantic layer: concepts, and the query engine over them."""

import difflib
from typing import TYPE_CHECKING, Any

from rootcause._http import Transport
from rootcause.errors import NotFoundInWorkspaceError

if TYPE_CHECKING:
    import pandas as pd

_ONTOLOGY_OPERATORS = {
    "eq": "eq", "==": "eq", "equals": "eq",
    "neq": "neq", "!=": "neq", "<>": "neq",
    "gt": "gt", ">": "gt",
    "gte": "gte", ">=": "gte",
    "lt": "lt", "<": "lt",
    "lte": "lte", "<=": "lte",
    "between": "between", "in": "in", "contains": "contains",
}


class OntologyQueryResult:
    """Rows out of the ontology query engine, plus the compiled dataset and any warnings."""

    def __init__(self, ontology: "Ontology", payload: dict[str, Any], request_body: dict[str, Any]) -> None:
        self._ontology = ontology
        self._request_body = request_body
        pagination = payload.get("pagination") or {}
        self.rows: list[dict[str, Any]] = list(payload.get("rows", []))
        self.next_cursor = pagination.get("cursor")
        self.schema = payload.get("schema", [])
        self.row_count = payload.get("rowCount")
        self.dataset = payload.get("dataset")
        self.warnings: list[str] = list(payload.get("warnings", []))
        self.summary = payload.get("summary")
        self.query = payload.get("query") or request_body.get("query")

    def to_frame(self, max_rows: int | None = None) -> "pd.DataFrame":
        import pandas as pd

        rows = list(self.rows)
        cursor = self.next_cursor
        while cursor is not None and (max_rows is None or len(rows) < max_rows):
            page = self._ontology._post_query({**self._request_body, "cursor": cursor})
            rows.extend(page.get("rows", []))
            cursor = (page.get("pagination") or {}).get("cursor")
        if max_rows is not None:
            rows = rows[:max_rows]
        frame = pd.DataFrame(rows)
        artifacts = [column for column in frame.columns if str(column).startswith("__index_level_")]
        return frame.drop(columns=artifacts)

    def __repr__(self) -> str:
        total = self.row_count if self.row_count is not None else f"{len(self.rows)}+"
        warn = f", warnings={len(self.warnings)}" if self.warnings else ""
        return f"OntologyQueryResult(rows={total}{warn})"

    def _repr_html_(self) -> str:
        import pandas as pd

        warnings_html = "".join(f"<li>{warning}</li>" for warning in self.warnings)
        prefix = f"<ul>{warnings_html}</ul>" if warnings_html else ""
        return f"<div>{prefix}{pd.DataFrame(self.rows).head(20)._repr_html_()}</div>"


class Ontology:
    """The workspace's semantic layer: concepts, and the query engine over them."""

    def __init__(self, transport: Transport, workspace_id: str) -> None:
        self._transport = transport
        self._workspace_id = workspace_id
        self._concept_cache: list[dict[str, Any]] | None = None

    def _base(self) -> str:
        return f"/api/v1/workspaces/{self._workspace_id}/ontology"

    def _concepts_raw(self, refresh: bool = False) -> list[dict[str, Any]]:
        if self._concept_cache is None or refresh:
            envelope = self._transport.request("GET", f"{self._base()}/concepts", params={"limit": 500})
            self._concept_cache = list(envelope.get("data", []))
        return self._concept_cache

    @property
    def concepts(self) -> "pd.DataFrame":
        import pandas as pd

        rows = [
            {
                "id": concept.get("id") or concept.get("_id"),
                "name": concept.get("name"),
                "type": concept.get("schemaType"),
                "classification": concept.get("conceptClassification"),
                "sources": len(concept.get("fieldMappings", [])),
            }
            for concept in self._concepts_raw()
        ]
        return pd.DataFrame(rows, columns=["id", "name", "type", "classification", "sources"])

    def __getitem__(self, name: str) -> dict[str, Any]:
        return self._resolve(name)

    def _ipython_key_completions_(self) -> list[str]:
        return [str(concept.get("name")) for concept in self._concepts_raw() if concept.get("name")]

    def _resolve(self, needle: str) -> dict[str, Any]:
        concepts = self._concepts_raw()
        for concept in concepts:
            if needle in (concept.get("id"), concept.get("_id"), concept.get("name")):
                return concept
        lowered = needle.lower()
        for concept in concepts:
            if str(concept.get("name", "")).lower() == lowered:
                return concept
        names = [str(concept.get("name")) for concept in concepts if concept.get("name")]
        raise NotFoundInWorkspaceError("ontology concept", needle, difflib.get_close_matches(needle, names, n=5))

    def _concept_id(self, needle: str) -> str:
        concept = self._resolve(needle)
        return str(concept.get("id") or concept.get("_id"))

    def query(
        self,
        select: list[str] | None = None,
        where: list[tuple[str, str, Any]] | None = None,
        group_by: list[str] | None = None,
        order_by: str | list[str] | None = None,
        aggregate: dict[str, str] | None = None,
        sources: list[str] | None = None,
        limit: int = 1000,
        wide: bool = True,
        page_size: int = 1000,
    ) -> OntologyQueryResult:
        """Execute a structured ontology query; concepts go by name or id.

        where clauses are (concept, operator, value) with operators
        eq/neq/gt/gte/lt/lte/between/in/contains or their symbols.
        """
        query: dict[str, Any] = {
            "conceptIds": [self._concept_id(name) for name in (select or [])],
            "filters": [
                {
                    "conceptId": self._concept_id(concept),
                    "operator": self._operator(operator),
                    "value": value,
                }
                for concept, operator, value in (where or [])
            ],
            "aggregations": [
                {"conceptId": self._concept_id(concept), "function": function}
                for concept, function in (aggregate or {}).items()
            ],
            "groupBy": [self._concept_id(name) for name in (group_by or [])],
            "orderBy": self._order(order_by),
            "sourceIds": sources or [],
            "wide": wide,
            "limit": limit,
        }
        body = {"query": query, "limit": page_size}
        return OntologyQueryResult(self, self._post_query(body), body)

    def ask(self, prompt: str, page_size: int = 1000) -> OntologyQueryResult:
        """Natural-language question, translated server-side; the structured query is echoed back."""
        body = {"prompt": prompt, "limit": page_size}
        payload = self._post_query(body)
        result = OntologyQueryResult(self, payload, {"query": payload.get("query"), "limit": page_size})
        return result

    def _post_query(self, body: dict[str, Any]) -> dict[str, Any]:
        envelope = self._transport.request("POST", f"{self._base()}/query", json_body=body)
        return envelope.get("data", envelope)

    def _operator(self, operator: str) -> str:
        resolved = _ONTOLOGY_OPERATORS.get(str(operator).strip().lower())
        if resolved is None:
            raise ValueError(f'Unknown operator "{operator}". Use one of {sorted(set(_ONTOLOGY_OPERATORS.values()))}')
        return resolved

    def _order(self, order_by: str | list[str] | None) -> list[dict[str, str]]:
        if order_by is None:
            return []
        entries = [order_by] if isinstance(order_by, str) else list(order_by)
        compiled = []
        for entry in entries:
            direction = "desc" if entry.startswith("-") else "asc"
            compiled.append({"conceptId": self._concept_id(entry.lstrip("+-")), "direction": direction})
        return compiled

    def __repr__(self) -> str:
        return f"Ontology(concepts={len(self._concepts_raw())})"
