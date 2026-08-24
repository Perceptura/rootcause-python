"""The workspace semantic layer: concepts, and the query engine over them."""

import difflib
from typing import TYPE_CHECKING, Any

from rootcause._http import Transport
from rootcause.errors import (
    AnchorSqlError,
    InvalidArgumentError,
    NotFoundInWorkspaceError,
    RootCauseApiError,
    RootCauseError,
)

if TYPE_CHECKING:
    from typing import NoReturn

    import pandas as pd


class AnchorSqlResult:
    """One Anchor SQL response: rows, a metadata listing, or a validated plan.

    Attributes:
        kind (str): `rows` for a materialised result, `metadata` for
            SHOW/DESCRIBE output, `validated` for a compile-only pass.
        rows (list[dict]): The first page of rows.
        columns (list[str]): Column order for the rows.
        units (dict[str, str]): Unit id per column, where the ontology knows
            one.
        row_count (int | None): Rows in this page.
        total_row_count (int | None): Total rows the statement matched, when
            the engine counted them.
        truncated (bool): Whether the result was cut at the engine's cap.
        next_start_key (int | None): Resume point for the next page — pass it
            back as `start_key=`, or let [`to_frame`](#to_frame) page for you.
            None when this page is the last.
        plan (dict): The compiled plan: scope, spine, join and grain chips,
            plus the join strategy the ontology chose.
        warnings (list[str]): Anything the planner wants you to know.
        statement (str): The statement as the engine echoed it back.
    """

    def __init__(self, ontology: "Ontology", payload: dict[str, Any], request_body: dict[str, Any]) -> None:
        self._ontology = ontology
        self._request_body = request_body
        self.kind = str(payload.get("kind") or "rows")
        self.rows: list[dict[str, Any]] = list(payload.get("rows") or [])
        self.columns: list[str] = [str(column) for column in payload.get("columns") or []]
        self.units: dict[str, str] = dict(payload.get("units") or {})
        self.row_count = payload.get("rowCount")
        self.total_row_count = payload.get("totalRowCount")
        self.truncated = bool(payload.get("truncated", False))
        self.next_start_key = payload.get("nextStartKey")
        self.plan: dict[str, Any] = dict(payload.get("plan") or {})
        self.warnings: list[str] = list(payload.get("warnings") or [])
        self.statement = str(payload.get("sql") or payload.get("command") or request_body.get("anchorSql", ""))

    def to_frame(self, max_rows: int | None = None) -> "pd.DataFrame":
        """Every row, paging transparently through `next_start_key`.

        Args:
            max_rows: Stop after this many rows. Fetches everything when
                omitted.

        Returns:
            The rows as a DataFrame, columns in engine order.
        """
        import pandas as pd

        rows = list(self.rows)
        start_key = self.next_start_key
        while start_key is not None and (max_rows is None or len(rows) < max_rows):
            page = self._ontology._post_sql({**self._request_body, "startKey": start_key})
            rows.extend(page.get("rows") or [])
            start_key = page.get("nextStartKey")
        if max_rows is not None:
            rows = rows[:max_rows]
        if self.columns:
            return pd.DataFrame(rows, columns=self.columns)
        return pd.DataFrame(rows)

    def __repr__(self) -> str:
        if self.kind != "rows":
            return f"AnchorSqlResult(kind={self.kind!r}, rows={len(self.rows)})"
        total = self.total_row_count if self.total_row_count is not None else self.row_count
        shown = len(self.rows) if total is None else total
        more = "+" if self.next_start_key is not None and total is None else ""
        warn = f", warnings={len(self.warnings)}" if self.warnings else ""
        return f"AnchorSqlResult(rows={shown}{more}{warn})"

    def _repr_html_(self) -> str:
        import pandas as pd

        warnings_html = "".join(f"<li>{warning}</li>" for warning in self.warnings)
        prefix = f"<ul>{warnings_html}</ul>" if warnings_html else ""
        return f"<div>{prefix}{pd.DataFrame(self.rows).head(20)._repr_html_()}</div>"


class Concept:
    """A handle to one ontology concept — resolve it once, then operate on it.

    Supports dict-style access to the underlying document
    (`concept["metadata"]`), so it drops in wherever the raw doc was used.
    """

    def __init__(self, ontology: "Ontology", doc: dict[str, Any]) -> None:
        self._ontology = ontology
        self.doc = doc

    @property
    def id(self) -> str:
        return str(self.doc.get("id") or self.doc.get("_id"))

    @property
    def name(self) -> str:
        return str(self.doc.get("name", self.id))

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self.doc.get("metadata") or {})

    @property
    def detected(self) -> dict[str, Any]:
        """What the auto-profiler detected, shadowing any overrides."""
        return dict(self.doc.get("detectedMetadata") or {})

    def __getitem__(self, key: str) -> Any:
        return self.doc[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.doc.get(key, default)

    def refresh(self) -> "Concept":
        """Re-read the concept from the platform."""
        self.doc = self._ontology._fetch_concept(self.id)
        return self

    def override(self, *, metadata: dict[str, Any] | None = None, **overrides: Any) -> "Concept":
        """Override this concept's metadata or structure, locked against re-profiling.

        See [`Ontology.override`](#override) for the keyword vocabulary.

        Returns:
            This handle, refreshed with the updated document.
        """
        self.doc = self._ontology.override(self, metadata=metadata, **overrides)
        return self

    def revert(self, *fields: str) -> "Concept":
        """Revert overridden fields to their detected values; all locked fields when none given.

        Returns:
            This handle, refreshed with the updated document.
        """
        self.doc = self._ontology.revert(self, *fields)
        return self

    @property
    def locks(self) -> "pd.DataFrame":
        """The overridden metadata fields: current value vs detected."""
        return self._ontology.locks(self)

    def __repr__(self) -> str:
        locked = len(self.doc.get("lockedMetadataFields") or [])
        suffix = f", overrides={locked}" if locked else ""
        return f"Concept({self.name!r}, type={self.doc.get('schemaType')}{suffix})"


class Ontology:
    """The workspace's semantic layer: concepts, and the query engine over them."""

    def __init__(self, transport: Transport, workspace_id: str) -> None:
        self._transport = transport
        self._workspace_id = workspace_id
        self._concept_cache: list[dict[str, Any]] | None = None

    def link(self) -> "Any":
        """The workspace's ontology page on the platform, as a clickable URL."""
        from rootcause._links import workspace_link

        return workspace_link(self._transport, self._workspace_id, "/ontology")

    def _base(self) -> str:
        return f"/api/v1/workspaces/{self._workspace_id}/ontology"

    def _concepts_raw(self, refresh: bool = True) -> list[dict[str, Any]]:
        # Always fresh by default: ontology analysis lands asynchronously after
        # ingest, and a stale listing makes brand-new concepts unresolvable.
        # The cache only serves tab completion between keystrokes.
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

    def __getitem__(self, name: str) -> "Concept":
        return Concept(self, self._resolve(name))

    def concept(self, needle: "str | Concept") -> "Concept":
        """Resolve a concept by name or id into a [`Concept`](#concept) handle.

        Raises when the name matches more than one concept — resolve those
        through [`matching`](#matching) or an id.
        """
        if isinstance(needle, Concept):
            return needle
        return Concept(self, self._resolve(needle))

    def matching(self, name: str) -> "list[Concept]":
        """Every concept whose name matches — the disambiguation escape hatch."""
        lowered = name.lower()
        return [
            Concept(self, doc)
            for doc in self._concepts_raw()
            if doc.get("name") == name or str(doc.get("name", "")).lower() == lowered
        ]

    def _ipython_key_completions_(self) -> list[str]:
        return [str(concept.get("name")) for concept in self._concepts_raw(refresh=False) if concept.get("name")]

    def _resolve(self, needle: str) -> dict[str, Any]:
        concepts = self._concepts_raw()
        # An id match is exact by construction; names are NOT unique — two
        # unmerged sources with the same column each mint a concept with the
        # same name, so a name match must refuse ambiguity rather than pick one.
        for concept in concepts:
            if needle in (concept.get("id"), concept.get("_id")):
                return concept
        matches = [c for c in concepts if c.get("name") == needle]
        if not matches:
            lowered = needle.lower()
            matches = [c for c in concepts if str(c.get("name", "")).lower() == lowered]
        if len(matches) > 1:
            described = "; ".join(
                f'{c.get("id") or c.get("_id")} (field "{c.get("schemaFieldName")}", '
                f'{len(c.get("fieldMappings") or [])} source(s))'
                for c in matches
            )
            raise RootCauseError(
                f'"{needle}" names {len(matches)} concepts in this workspace — '
                f"pass the concept id instead: {described}"
            )
        if matches:
            return matches[0]
        names = [str(concept.get("name")) for concept in concepts if concept.get("name")]
        raise NotFoundInWorkspaceError("ontology concept", needle, difflib.get_close_matches(needle, names, n=5))

    def _concept_id(self, needle: "str | Concept") -> str:
        if isinstance(needle, Concept):
            return needle.id
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
        needle: "str | Concept",
        metadata: dict[str, Any],
        concept_fields: dict[str, Any],
    ) -> dict[str, Any]:
        concept_id = self._concept_id(needle)
        concept = self._fetch_concept(concept_id)
        body: dict[str, Any] = {"_id": concept_id, "editVersion": concept.get("editVersion", 0), **concept_fields}
        if metadata:
            body["metadata"] = metadata
        try:
            self._put_concept(concept_id, body)
        except RootCauseApiError as error:
            if error.status != 409:
                raise
            # concept changed underneath us — re-read for the fresh editVersion and retry once
            fresh = self._fetch_concept(concept_id)
            body["editVersion"] = fresh.get("editVersion", 0)
            self._put_concept(concept_id, body)
        # the write path answers a status envelope on some deployments; the
        # re-read is the authoritative updated document either way
        return self._fetch_concept(concept_id)

    def override(self, concept: "str | Concept", *, metadata: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
        """Override a concept's metadata or structure, locked against re-profiling.

        Overridden metadata fields are marked as human-set: the auto-profiler
        preserves them on every future ingest, and the detected value keeps
        shadowing underneath (see [`revert`](#revert)). Setting a field back
        to its detected value unlocks it again.

        The idiomatic flow resolves the concept once and operates on the
        [`Concept`](#concept) handle:

        ```python
        revenue = onto["Revenue"]
        revenue.override(monotonically_increasing=True, min_value=0)
        revenue.override(unit="GBP", nan_fill_strategy="interpolate")
        revenue.revert("unit")
        ```

        This method also accepts a name or id directly as a convenience.

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

    def revert(self, concept: "str | Concept", *fields: str) -> dict[str, Any]:
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

    def locks(self, concept: "str | Concept") -> "pd.DataFrame":
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

    def sql(self, statement: str, *, limit: int = 1000, start_key: int | None = None) -> AnchorSqlResult:
        """Run an Anchor SQL statement over the workspace's concepts.

        Anchor SQL is SQL over ontology concepts, not tables. Concepts go by
        quoted name, and the ontology plans the joins across every mapped
        source — there are no tables to FROM and no JOINs to write
        (`FROM source:"name"` exists only to narrow scope). The reserved
        anchors `entity`, `time` and `location` take grains like `time(month)`
        or `location(country)`; aggregates with GROUP BY / HAVING / ORDER BY /
        LIMIT work as in SQL, and metrics defined in the workspace are
        referenced by name verbatim. `SHOW CONCEPTS`, `SHOW METRICS`,
        `SHOW SOURCES` and `DESCRIBE "x"` answer metadata about what there is
        to query.

        ```python
        onto.sql('SELECT "Monthly Charges" WHERE "Contract" = \\'Month-to-month\\'')
        onto.sql('SELECT time(month), avg("Revenue") GROUP BY time(month)')
        onto.sql("SHOW CONCEPTS")
        onto.sql('DESCRIBE "Revenue"')
        ```

        Args:
            statement: The Anchor SQL statement.
            limit: Rows per page, 1 to 10000.
            start_key: Resume paging from a previous result's
                `next_start_key`. [`to_frame`](#to_frame) pages transparently,
                so this is only for driving pages by hand.

        Returns:
            An [`AnchorSqlResult`](#anchorsqlresult) — rows for a SELECT,
            a metadata listing for SHOW/DESCRIBE.

        Raises:
            AnchorSqlError: The engine refused the statement; carries the
                error code, the offending span, near-miss candidates and a
                suggested corrected statement when the engine has one.
        """
        if not str(statement).strip():
            raise InvalidArgumentError(
                "statement= is empty; pass an Anchor SQL statement (SHOW CONCEPTS lists what there is to query)"
            )
        body: dict[str, Any] = {"anchorSql": statement, "limit": limit}
        if start_key is not None:
            body["startKey"] = start_key
        return AnchorSqlResult(self, self._post_sql(body), body)

    def query(self, *args: Any, **kwargs: Any) -> "NoReturn":
        """Removed — the query endpoint now speaks Anchor SQL; use [`sql`](#sql)."""
        raise RootCauseError(
            "Ontology.query() was removed: the platform's ontology query engine now speaks Anchor SQL. "
            "Rewrite the query with onto.sql() — "
            "query(select=[\"Revenue\"], where=[(\"Region\", \"==\", \"US\")], aggregate={\"Revenue\": \"sum\"}) "
            "becomes onto.sql('SELECT sum(\"Revenue\") WHERE \"Region\" = \\'US\\''). "
            "onto.sql(\"SHOW CONCEPTS\") lists what you can reference."
        )

    def ask(self, *args: Any, **kwargs: Any) -> "NoReturn":
        """Removed — server-side translation is gone; write Anchor SQL with [`sql`](#sql)."""
        raise RootCauseError(
            "Ontology.ask() was removed: the platform no longer translates prompts server-side. "
            "Write the question as Anchor SQL with onto.sql() — concepts go by quoted name, "
            "e.g. onto.sql('SELECT \"customer\", avg(\"Revenue\") GROUP BY \"customer\"'). "
            "onto.sql(\"SHOW CONCEPTS\") lists what you can reference."
        )

    def _post_sql(self, body: dict[str, Any]) -> dict[str, Any]:
        envelope = self._transport.request("POST", f"{self._base()}/query", json_body=body)
        payload = envelope.get("data", envelope)
        if isinstance(payload, dict) and payload.get("ok") is False:
            raise AnchorSqlError(payload.get("error"))
        return payload

    def __repr__(self) -> str:
        return f"Ontology(concepts={len(self._concepts_raw())})"