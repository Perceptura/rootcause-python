"""The workspace semantic layer: concepts, and the query engine over them."""

import difflib
from typing import TYPE_CHECKING, Any

from rootcause._http import Transport
from rootcause.errors import NotFoundInWorkspaceError, RootCauseApiError, RootCauseError

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
    """Rows out of the ontology query engine, plus the compiled dataset and any warnings.

    Attributes:
        rows (list[dict]): The first page of rows.
        row_count (int | None): Total rows the query matched.
        schema (list): Column schema for the rows.
        warnings (list[str]): Anything the engine wants you to know about the
            join.
        dataset (dict | None): The compiled dataset definition, persistable via
            the API.
        query (dict | None): For `ask()`, the structured query the translator
            produced.
        next_cursor (str | None): Cursor for the next page, when there is one.
        summary (str | None): The engine's narrative summary, when it made one.
    """

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
        """Every row, paging transparently.

        Args:
            max_rows: Stop after this many rows. Fetches everything when
                omitted.

        Returns:
            The rows as a DataFrame.
        """
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

    # Metadata overrides accepted as keyword arguments, mapped to the concept's
    # metadata field names. Anything else goes through the metadata= dict.
    _METADATA_KWARGS = {
        "monotonically_increasing": "isMonotonicallyIncreasing",
        "monotonically_decreasing": "isMonotonicallyDecreasing",
        "min_value": "minValue",
        "max_value": "maxValue",
        "unit": "unit",
        "unit_modifier": "unitModifier",
        "nan_fill_strategy": "nanFillStrategy",
        "categories": "categories",
        "date_time_format": "dateTimeFormat",
        "display_format": "displayFormat",
        "is_cyclic": "isCyclic",
        "is_unique": "isUnique",
    }

    # Concept-level (non-metadata) overrides. Only fields present in the update
    # body count as edited, so these are sent exclusively when passed.
    _CONCEPT_KWARGS = {
        "name": "name",
        "description": "description",
        "classification": "conceptClassification",
        "schema_type": "schemaType",
        "schema_subtype": "schemaSubtype",
        "suggested_role": "suggestedRole",
        "temporal_prerequisites": "temporalPrerequisites",
    }

    def _fetch_concept(self, concept_id: str) -> dict[str, Any]:
        envelope = self._transport.request("GET", f"{self._base()}/concepts/{concept_id}")
        return envelope.get("data", envelope)

    def _put_concept(self, concept_id: str, body: dict[str, Any]) -> dict[str, Any]:
        envelope = self._transport.request("PUT", f"{self._base()}/concepts/{concept_id}", json_body=body)
        self._concept_cache = None
        return envelope.get("data", envelope)

    def _apply_update(
        self,
        needle: str,
        metadata: dict[str, Any],
        concept_fields: dict[str, Any],
    ) -> dict[str, Any]:
        concept_id = self._concept_id(needle)
        concept = self._fetch_concept(concept_id)
        body: dict[str, Any] = {"_id": concept_id, "editVersion": concept.get("editVersion", 0), **concept_fields}
        if metadata:
            body["metadata"] = metadata
        try:
            return self._put_concept(concept_id, body)
        except RootCauseApiError as error:
            if error.status != 409:
                raise
            # concept changed underneath us — re-read for the fresh editVersion and retry once
            fresh = self._fetch_concept(concept_id)
            body["editVersion"] = fresh.get("editVersion", 0)
            return self._put_concept(concept_id, body)

    def override(self, concept: str, *, metadata: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
        """Override a concept's metadata or structure, locked against re-profiling.

        Overridden metadata fields are marked as human-set: the auto-profiler
        preserves them on every future ingest, and the detected value keeps
        shadowing underneath (see [`revert`](#revert)). Setting a field back
        to its detected value unlocks it again.

        ```python
        onto.override("cumulative_revenue", monotonically_increasing=True, min_value=0)
        onto.override("temperature", unit="°C", nan_fill_strategy="interpolate")
        onto.override("churn", suggested_role="target", description="Did the customer leave")
        ```

        Args:
            concept: Concept name or id.
            metadata: Any concept metadata field by its camelCase name, for
                fields without a keyword below.
            **overrides: Metadata keywords — `monotonically_increasing`,
                `monotonically_decreasing`, `min_value`, `max_value`, `unit`,
                `unit_modifier`, `nan_fill_strategy`, `categories`,
                `date_time_format`, `display_format`, `is_cyclic`,
                `is_unique` — and concept-level `name`, `description`,
                `classification`, `schema_type`, `schema_subtype`,
                `suggested_role`, `temporal_prerequisites`.

        Returns:
            The updated concept document.
        """
        metadata_update: dict[str, Any] = dict(metadata or {})
        concept_update: dict[str, Any] = {}
        unknown: list[str] = []
        for key, value in overrides.items():
            if key in self._METADATA_KWARGS:
                metadata_update[self._METADATA_KWARGS[key]] = value
            elif key in self._CONCEPT_KWARGS:
                concept_update[self._CONCEPT_KWARGS[key]] = value
            else:
                unknown.append(key)
        if unknown:
            known = sorted([*self._METADATA_KWARGS, *self._CONCEPT_KWARGS])
            raise RootCauseError(
                f"Unknown override(s) {unknown}; known keywords: {', '.join(known)} "
                f"(or pass metadata={{...}} with the field's camelCase name)"
            )
        if not metadata_update and not concept_update:
            raise RootCauseError("Nothing to override — pass at least one field")
        return self._apply_update(concept, metadata_update, concept_update)

    def revert(self, concept: str, *fields: str) -> dict[str, Any]:
        """Revert overridden metadata fields to their auto-detected values.

        Setting a field back to its detected value also unlocks it, so the
        profiler owns it again on future ingests.

        Args:
            concept: Concept name or id.
            *fields: Fields to revert, as `override` keywords or camelCase
                metadata names. With none, every locked field reverts.

        Returns:
            The updated concept document.
        """
        concept_id = self._concept_id(concept)
        doc = self._fetch_concept(concept_id)
        detected = doc.get("detectedMetadata")
        locked = list(doc.get("lockedMetadataFields") or [])
        if not detected:
            raise RootCauseError(f'Concept "{concept}" has no detected metadata to revert to')
        wanted = [self._METADATA_KWARGS.get(f, f) for f in fields] if fields else locked
        missing = [f for f in wanted if f not in locked]
        if missing:
            raise RootCauseError(f"Not overridden (nothing to revert): {missing}; locked fields: {locked or 'none'}")
        metadata = {f: detected.get(f) for f in wanted}
        return self._apply_update(concept, metadata, {})

    def locks(self, concept: str) -> "pd.DataFrame":
        """The concept's overridden metadata fields: current value vs detected.

        Args:
            concept: Concept name or id.

        Returns:
            One row per locked field, with `value` and `detected` columns.
        """
        import pandas as pd

        doc = self._fetch_concept(self._concept_id(concept))
        metadata = doc.get("metadata") or {}
        detected = doc.get("detectedMetadata") or {}
        rows = [
            {"field": f, "value": metadata.get(f), "detected": detected.get(f)}
            for f in (doc.get("lockedMetadataFields") or [])
        ]
        return pd.DataFrame(rows, columns=["field", "value", "detected"])

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

        Args:
            select: Concepts to return, by name or id.
            where: Filters as `(concept, operator, value)`. Operators are
                `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `between`, `in`,
                `contains`, or their symbols.
            group_by: Concepts to group by.
            order_by: Concept, or concepts, to order by.
            aggregate: Aggregate function per concept, as
                `{"Revenue": "sum"}`.
            sources: Restrict the query to these source ids.
            limit: Row cap on the whole query.
            wide: Return one column per concept rather than long format.
            page_size: Rows per page fetched from the API.

        Returns:
            An [`OntologyQueryResult`](#ontologyqueryresult).
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
        """Natural-language question, translated server-side.

        Args:
            prompt: The question, in plain language.
            page_size: Rows per page fetched from the API.

        Returns:
            An [`OntologyQueryResult`](#ontologyqueryresult); `result.query` is
            the structured query the translator produced.
        """
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