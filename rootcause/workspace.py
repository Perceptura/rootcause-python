"""Platform-mode handles: a workspace and the sources, views, and connectors in it."""

import difflib
import time
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from rootcause import _guard
from rootcause._http import Transport, expect, poll_job
from rootcause.errors import (
    InvalidArgumentError,
    MalformedResponseError,
    NotFoundInWorkspaceError,
    RootCauseError,
)
from rootcause.ontology import Ontology
from rootcause.twin import Twin

if TYPE_CHECKING:
    import pandas as pd

    from rootcause._links import PlatformLink


class _Collection:
    """Name-or-id addressable collection over a list endpoint, with live completions."""

    kind = "object"

    def __init__(self, fetch: Callable[[], list[dict[str, Any]]], wrap: Callable[[dict[str, Any]], Any]) -> None:
        self._fetch = fetch
        self._wrap = wrap

    def _docs(self) -> list[dict[str, Any]]:
        return self._fetch()

    def to_frame(self) -> "pd.DataFrame":
        import pandas as pd

        rows = [
            {"id": doc.get("id") or doc.get("_id"), "name": doc.get("name")}
            for doc in self._docs()
        ]
        return pd.DataFrame(rows, columns=["id", "name"])

    def __iter__(self) -> Iterator[Any]:
        return (self._wrap(doc) for doc in self._docs())

    def __len__(self) -> int:
        return len(self._docs())

    def __getitem__(self, needle: str) -> Any:
        docs = self._docs()
        for doc in docs:
            if needle in (doc.get("id"), doc.get("_id"), doc.get("name")):
                return self._wrap(doc)
        lowered = needle.lower()
        for doc in docs:
            if str(doc.get("name", "")).lower() == lowered:
                return self._wrap(doc)
        names = [str(doc.get("name")) for doc in docs if doc.get("name")]
        raise NotFoundInWorkspaceError(self.kind, needle, difflib.get_close_matches(needle, names, n=5))

    def get(self, needle: str, default: Any = None) -> Any:
        try:
            return self[needle]
        except NotFoundInWorkspaceError:
            return default

    def _ipython_key_completions_(self) -> list[str]:
        return [str(doc.get("name")) for doc in self._docs() if doc.get("name")]

    def __repr__(self) -> str:
        names = self._ipython_key_completions_()
        preview = ", ".join(names[:8]) + ("…" if len(names) > 8 else "")
        return f"<{len(names)} {self.kind}s: {preview}>"


class Source:
    """An ingested data source — raw rows as imported."""

    def __init__(self, transport: Transport, workspace_id: str, doc: dict[str, Any]) -> None:
        self._transport = transport
        self._workspace_id = workspace_id
        self.doc = doc

    def delete(self, *, force: bool = False) -> None:
        """Delete this source and every source derived from it. Requires the `sources:delete` scope.

        Refused while a twin was trained on any of them — those twins would keep
        their ids and lose their history, backtests and any relink target — and
        refused while the source is shared into other workspaces, since deleting
        it removes it from those too. Both errors say what blocks it.

        Args:
            force: Delete through both refusals.
        """
        self._transport.request("DELETE", self._path(), params={"force": "true"} if force else None)

    def link(self) -> "PlatformLink":
        """The source's detail page on the platform, as a clickable URL."""
        from rootcause._links import workspace_link

        return workspace_link(self._transport, self._workspace_id, f"/sources/{self.id}")

    @property
    def id(self) -> str:
        return str(self.doc.get("id") or self.doc.get("_id"))

    @property
    def name(self) -> str:
        return str(self.doc.get("name", self.id))

    @property
    def read_mode(self) -> str:
        """How this source is read: `"direct_query"` or `"snapshot"`.

        A direct-query source is read from its origin database on every query, so its rows are
        always current, every read costs a remote scan subject to that database's statement
        timeout, and no row count is recorded. A snapshot is a stored copy, which changes only
        when it is synced.
        """
        return str(self.doc.get("readMode", "snapshot"))

    @property
    def direct_query(self) -> dict[str, Any] | None:
        """The settings a direct-query source is read with, or `None` where it is a snapshot.

        `orderingColumn` is what the rows are paged by, and `statementTimeoutSeconds` and
        `maxRowsScanned` are the caps a wide query has to stay inside.
        """
        settings = self.doc.get("directQuery")
        return dict(settings) if isinstance(settings, dict) else None

    @property
    def dropped_columns(self) -> list[dict[str, str]]:
        """Columns the remote has that this source does not, because the platform has no type for
        them. Only ever non-empty on a source just created over an object store."""
        return list(self.doc.get("droppedColumns") or [])

    def _path(self) -> str:
        return f"/api/v1/workspaces/{self._workspace_id}/sources/{self.id}"

    @property
    def schema(self) -> "pd.DataFrame":
        import pandas as pd

        envelope = self._transport.request("GET", f"{self._path()}/schema")
        entries = envelope.get("data", envelope)
        if isinstance(entries, dict):
            entries = entries.get("schemaEntries") or entries.get("schema") or []
        return pd.DataFrame(entries)

    def to_frame(self) -> "pd.DataFrame":
        blob = self._transport.request_bytes("GET", f"{self._path()}/export/parquet")
        return _guard.from_parquet(blob, f'source "{self.name}"')

    def extend(self, frame: "pd.DataFrame") -> None:
        """Append new rows to this source. Blocks until the rows are ingested.

        Args:
            frame: Rows to append. The schema must match the source.

        Raises:
            InvalidArgumentError: `frame` is not a usable, non-empty DataFrame.
        """
        content = _guard.to_parquet(_guard.frame(frame))
        self._transport.request(
            "POST",
            f"{self._path()}/extend",
            content=content,
            headers={"Content-Type": "application/octet-stream", "x-filename": f"{self.name}-extend.parquet"},
        )

    def __repr__(self) -> str:
        return f"Source({self.name!r}, id={self.id})"


class Dataset:
    """A derived, queryable dataset built from one or more sources."""

    def __init__(self, transport: Transport, workspace_id: str, doc: dict[str, Any]) -> None:
        self._transport = transport
        self._workspace_id = workspace_id
        self.doc = doc

    def delete(self) -> None:
        """Delete this dataset permanently. Requires the `datasets:delete` scope.

        Twins trained on it keep their fitted models but cannot retrain until
        repointed at another dataset.
        """
        self._transport.request("DELETE", self._path())

    def link(self) -> "PlatformLink":
        """The dataset's page on the platform, as a clickable URL."""
        from rootcause._links import workspace_link

        return workspace_link(self._transport, self._workspace_id, f"/datasets/{self.id}")

    @property
    def id(self) -> str:
        return str(self.doc.get("id") or self.doc.get("_id"))

    @property
    def name(self) -> str:
        return str(self.doc.get("name", self.id))

    def _path(self) -> str:
        return f"/api/v1/workspaces/{self._workspace_id}/datasets/{self.id}"

    @property
    def schema(self) -> "pd.DataFrame":
        import pandas as pd

        envelope = self._transport.request("GET", f"{self._path()}/schema")
        entries = envelope.get("data", envelope)
        if isinstance(entries, dict):
            entries = entries.get("schemaEntries") or entries.get("schema") or []
        return pd.DataFrame(entries)

    def to_frame(self) -> "pd.DataFrame":
        blob = self._transport.request_bytes("GET", f"{self._path()}/export/parquet")
        return _guard.from_parquet(blob, f'dataset "{self.name}"')

    def records(self, limit: int = 100, cursor: str | None = None) -> list[dict[str, Any]]:
        """One page of rows as dicts.

        Args:
            limit: Rows per page.
            cursor: The previous page's cursor, to continue from it.

        Returns:
            The page's rows.
        """
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        envelope = self._transport.request("GET", f"{self._path()}/records", params=params)
        return list(envelope.get("data", []))

    def __repr__(self) -> str:
        return f"Dataset({self.name!r}, id={self.id})"


class Connector:
    """An organisation-level connector to an external system (Snowflake, S3, …)."""

    def __init__(self, transport: Transport, workspace_id: str, doc: dict[str, Any]) -> None:
        self._transport = transport
        self._workspace_id = workspace_id
        self.doc = doc

    @property
    def id(self) -> str:
        return str(self.doc.get("id") or self.doc.get("_id"))

    @property
    def name(self) -> str:
        return str(self.doc.get("name", self.id))

    def test(self) -> dict[str, Any]:
        """Validate that the stored credentials can reach the external system."""
        envelope = self._transport.request("POST", f"/api/v1/connectors/{self.id}/test")
        return envelope.get("data", envelope)

    def browse(self, level: str, **context: str) -> Any:
        """Walk the external system's hierarchy one level at a time.

        Args:
            level: Which level to list, for example `databases` or `tables`.
            **context: The levels already chosen, narrowing the listing.

        Returns:
            The listing for that level.
        """
        envelope = self._transport.request(
            "GET", f"/api/v1/connectors/{self.id}/browse", params={"level": level, **context}
        )
        return envelope.get("data", envelope)

    def query(self, query: str, *, limit: int = 100, **config: Any) -> "pd.DataFrame":
        """Run a custom query against the external system and return sample rows.

        The authoring loop for custom SQL: nothing is stored, database errors
        come back verbatim.

        Args:
            query: The SQL to run.
            limit: Row cap on the sample that comes back.
            **config: Connector config overrides, for example `database=`,
                `warehouse=`, `schema=`.

        Returns:
            The sample rows as a DataFrame.

        Raises:
            RootCauseError: The external system rejected the query. Its error is
                quoted verbatim.
        """
        import pandas as pd

        envelope = self._transport.request(
            "POST",
            f"/api/v1/connectors/{self.id}/preview-query",
            json_body={"config": {"query": query, **config}, "limit": limit},
        )
        data = envelope.get("data", envelope)
        if not isinstance(data, dict):
            raise MalformedResponseError(f"The query preview answered {type(data).__name__}, not a result payload")
        if not data.get("success", False):
            raise RootCauseError(f"Query preview failed: {data.get('error', 'unknown error')}")
        columns = [c["name"] for c in data.get("columns", [])]
        return pd.DataFrame(data.get("rows", []), columns=columns)

    def import_table(self, table: str, *, name: str | None = None, timeout: float = 3600.0, **config: Any) -> Source:
        """Import one table into the workspace as a new source.

        Args:
            table: Table to import.
            name: Name for the new source. Derived from the table when omitted.
            timeout: Seconds to wait for the import job.
            **config: Connector config overrides, for example `database=`,
                `schema=`.

        Returns:
            The new [`Source`](#source).
        """
        return self.run_import({"table": table, **config}, dataset_name=name, timeout=timeout)

    def import_query(self, query: str, *, name: str | None = None, timeout: float = 3600.0, **config: Any) -> Source:
        """Import the result of a custom query into the workspace as a new source.

        Args:
            query: The SQL whose result becomes the source.
            name: Name for the new source.
            timeout: Seconds to wait for the import job.
            **config: Connector config overrides.

        Returns:
            The new [`Source`](#source).
        """
        return self.run_import({"query": query, **config}, dataset_name=name, timeout=timeout)

    def direct_query_table(
        self,
        table: str,
        *,
        ordering_column: str,
        name: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        warehouse: str | None = None,
        append_only: bool = False,
        statement_timeout_seconds: int | None = None,
        max_rows_scanned: int | None = None,
        relation: str | None = None,
        parent_id: str | None = None,
    ) -> Source:
        """Read one table where it lives instead of importing a copy of it.

        The source is created from the remote's catalogue rather than ingested, so this returns
        at once and there is no job to wait on — but every query against it then runs against
        the origin database and is subject to its statement timeout. Import instead when the
        data must be stable and queried repeatedly and cheaply.

        Supported on PostgreSQL, MySQL, Snowflake and ClickHouse; storage connectors are pointed
        at a path, so use [`create_direct_query_source`](#create_direct_query_source) for those.

        Args:
            table: Table to read.
            ordering_column: Column the rows are paged by. Required, and it should be unique and
                non-null: rows are paged straight from the remote, and without a stable sort the
                same row can appear on two pages or none.
            name: Name for the new source. Derived from the table when omitted.
            database: Database the table is in, where it is not the connector's own.
            schema: Schema the table is in (PostgreSQL and Snowflake).
            warehouse: Warehouse to run against (Snowflake).
            append_only: Declare that rows are only ever added, never updated or deleted.
            statement_timeout_seconds: Cap on how long one remote statement may run.
            max_rows_scanned: Cap on how many rows one remote statement may scan.
            relation: Relation to read, where it is not `table`.
            parent_id: Folder to create the source under.

        Returns:
            The new [`Source`](#source), already queryable.

        Raises:
            RootCauseError: The connector cannot be queried directly, or the settings are ones a
                direct query cannot honour. The reason says which.
            TypeError: An argument this does not take. Every setting is named here rather than
                swept into the connector selection, because one that reached the selection would
                be accepted by the API, ignored, and leave a source with no cap and no complaint.
        """
        selection: dict[str, Any] = {"table": table}
        if database is not None:
            selection["database"] = database
        if schema is not None:
            selection["schema"] = schema
        if warehouse is not None:
            selection["warehouse"] = warehouse

        return self.create_direct_query_source(
            selection,
            ordering_column=ordering_column,
            name=name or table,
            append_only=append_only,
            statement_timeout_seconds=statement_timeout_seconds,
            max_rows_scanned=max_rows_scanned,
            relation=relation,
            parent_id=parent_id,
        )

    def create_direct_query_source(
        self,
        config: dict[str, Any],
        *,
        ordering_column: str,
        name: str,
        append_only: bool = False,
        statement_timeout_seconds: int | None = None,
        max_rows_scanned: int | None = None,
        relation: str | None = None,
        parent_id: str | None = None,
    ) -> Source:
        """Create a directly-queried source from a raw, connector-specific selection.

        The escape hatch under [`direct_query_table`](#direct_query_table), and the way to point
        a direct query at a storage connector: `{"path": "lake/readings"}` for S3, Google Cloud
        Storage and Azure Data Lake, which are read in place as Parquet.

        Args:
            config: The connector's own selection payload.
            ordering_column: Column the rows are paged by.
            name: Name for the new source.
            append_only: Declare that rows are only ever added, never updated or deleted. Lets a
                digital twin pin its training window by watermark instead of copying the rows.
            statement_timeout_seconds: Cap on how long one remote statement may run.
            max_rows_scanned: Cap on how many rows one remote statement may scan. SQL connectors
                only — a row cap has no file analogue, so storage connectors refuse it.
            relation: Relation to read, where it is not the config's table or resolved from the
                bucket and path.
            parent_id: Folder to create the source under; omitted files it at the workspace root.

        Returns:
            The new [`Source`](#source). Columns the remote has that the platform has no type
            for are left out, and listed on the source's `droppedColumns`.
        """
        body: dict[str, Any] = {
            "workspaceId": self._workspace_id,
            "datasetName": name,
            "config": config,
            "orderingColumn": ordering_column,
            "appendOnly": append_only,
        }
        if statement_timeout_seconds is not None:
            body["statementTimeoutSeconds"] = statement_timeout_seconds
        if max_rows_scanned is not None:
            body["maxRowsScanned"] = max_rows_scanned
        if relation is not None:
            body["relation"] = relation
        if parent_id is not None:
            body["parentId"] = parent_id

        envelope = self._transport.request(
            "POST",
            f"/api/v1/connectors/{self.id}/direct-query",
            json_body=body,
        )
        created = envelope.get("data", envelope)
        source_id = expect(envelope, "sourceId", "directly-queried source")
        doc = self._transport.request(
            "GET", f"/api/v1/workspaces/{self._workspace_id}/sources/{source_id}"
        )
        source = Source(self._transport, self._workspace_id, dict(doc.get("data", doc)))
        source.doc["droppedColumns"] = list(created.get("droppedColumns") or []) if isinstance(created, dict) else []
        return source

    def run_import(self, config: dict[str, Any], *, dataset_name: str | None = None, timeout: float = 3600.0) -> Source:
        """Import with a raw, connector-specific payload.

        The escape hatch under `import_table` and `import_query`.

        Args:
            config: The connector's own import payload.
            dataset_name: Name for the new source.
            timeout: Seconds to wait for the import job.

        Returns:
            The new [`Source`](#source).
        """
        body: dict[str, Any] = {"workspaceId": self._workspace_id, "config": config}
        if dataset_name:
            body["datasetName"] = dataset_name
        envelope = self._transport.request(
            "POST",
            f"/api/v1/connectors/{self.id}/import",
            json_body=body,
        )
        job_id = expect(envelope, "jobId", "import job")
        job = poll_job(self._transport, self._workspace_id, job_id, label=f"import {self.name}", timeout=timeout)
        dataset_id = job.get("domainEntityId") or job.get("datasetId")
        listing = self._transport.request("GET", f"/api/v1/workspaces/{self._workspace_id}/sources")
        docs = list(listing.get("data", []))
        for doc in docs:
            if dataset_id and (doc.get("id") == dataset_id or doc.get("_id") == dataset_id):
                return Source(self._transport, self._workspace_id, doc)
        if docs:
            newest = max(docs, key=lambda d: str(d.get("createdAt", "")))
            return Source(self._transport, self._workspace_id, newest)
        raise RootCauseError("Import finished but no dataset was found in the workspace")

    def __repr__(self) -> str:
        return f"Connector({self.name!r}, type={self.doc.get('type')})"


class Workspace:
    """A workspace handle: sources, datasets (views), twins, connectors, ontology."""

    def __init__(self, transport: Transport, doc: dict[str, Any]) -> None:
        self._transport = transport
        self.doc = doc
        self.ontology = Ontology(transport, self.id)

    def link(self) -> "PlatformLink":
        """The workspace's home page on the platform, as a clickable URL."""
        from rootcause._links import workspace_link

        return workspace_link(self._transport, self.id)

    @property
    def id(self) -> str:
        return str(self.doc.get("id") or self.doc.get("_id"))

    @property
    def name(self) -> str:
        return str(self.doc.get("name", self.id))

    def _list(self, path: str) -> list[dict[str, Any]]:
        envelope = self._transport.request("GET", f"/api/v1/workspaces/{self.id}{path}")
        return list(envelope.get("data", []))

    @property
    def sources(self) -> _Collection:
        collection = _Collection(lambda: self._list("/sources"), lambda doc: Source(self._transport, self.id, doc))
        collection.kind = "source"
        return collection

    @property
    def datasets(self) -> _Collection:
        collection = _Collection(lambda: self._list("/datasets"), lambda doc: Dataset(self._transport, self.id, doc))
        collection.kind = "dataset"
        return collection

    @property
    def twins(self) -> _Collection:
        collection = _Collection(lambda: self._list("/digital-twins"), lambda doc: Twin(self._transport, self.id, doc))
        collection.kind = "twin"
        return collection

    @property
    def connectors(self) -> _Collection:
        def fetch() -> list[dict[str, Any]]:
            envelope = self._transport.request("GET", "/api/v1/connectors")
            return list(envelope.get("data", []))

        collection = _Collection(fetch, lambda doc: Connector(self._transport, self.id, doc))
        collection.kind = "connector"
        return collection

    def add_connector(self, name: str, type: str, **credentials: Any) -> Connector:
        """Register a connector to an external system (credentials are stored encrypted).

        Args:
            name: Name for the connector.
            type: Connector type, for example `PostgreSQL` or `Snowflake`.
                One of the platform's connector type ids, matched exactly: the
                value is case-sensitive.
            **credentials: The connector's credentials. Stored encrypted, and
                never returned by the API.

        Returns:
            The registered [`Connector`](#connector).
        """
        envelope = self._transport.request(
            "POST",
            "/api/v1/connectors",
            json_body={"name": name, "type": type, "credentials": {"type": type, **credentials} if credentials else None},
        )
        doc = envelope.get("data", envelope)
        return Connector(self._transport, self.id, doc)

    def dataset(self, needle: str) -> Dataset:
        return self.datasets[needle]

    def source(self, needle: str) -> Source:
        return self.sources[needle]

    def twin(self, needle: str) -> Twin:
        return self.twins[needle]

    def upload(self, frame: "pd.DataFrame", name: str, *, wait: bool = True, timeout: float = 600.0) -> Source:
        """Upload a DataFrame as a new source (parquet on the wire, full ingest server-side).

        Args:
            frame: The data to upload.
            name: Name for the new source.
            wait: Block until the schema materialises server side.
            timeout: Seconds to wait for ingest, when `wait` is True.

        Returns:
            The new [`Source`](#source).

        Raises:
            InvalidArgumentError: `frame` is not a usable, non-empty DataFrame,
                or `name` is blank.
        """
        content = _guard.to_parquet(_guard.frame(frame))
        if not str(name).strip():
            raise InvalidArgumentError("name= is blank; a source needs a name to be findable again")

        created = self._transport.request(
            "POST", f"/api/v1/workspaces/{self.id}/sources", json_body={"name": name}
        )
        doc = created.get("data", created)
        source = Source(self._transport, self.id, doc)

        self._transport.request(
            "POST",
            f"/api/v1/workspaces/{self.id}/sources/{source.id}/upload",
            content=content,
            headers={"Content-Type": "application/octet-stream", "x-filename": f"{name}.parquet"},
        )

        if wait:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                schema = source.schema
                if len(schema) > 0:
                    break
                time.sleep(3.0)
            else:
                raise RootCauseError(f'Upload of "{name}" accepted but ingest produced no schema within {timeout:.0f}s')
        return source

    def create_twin(
        self,
        name: str,
        *,
        kind: str = "static",
        dataset_id: str | None = None,
        source_id: str | None = None,
        time_column: str | None = None,
        environment_columns: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> Twin:
        """Create a twin over a dataset, or directly over a raw source.

        Args:
            name: Name for the twin.
            kind: One of `static`, `temporal`, `multi-environment-static`,
                `multi-environment-temporal`.
            dataset_id: Dataset to train on. Pass this or `source_id`.
            source_id: Raw source to train on, skipping the dataset step.
            time_column: Time column, for temporal kinds.
            environment_columns: Columns that identify an environment, for panel
                kinds.
            tags: Tags to file the twin under.

        Returns:
            The new [`Twin`](#twin), untrained.

        Raises:
            InvalidArgumentError: Both, or neither, of `dataset_id` and
                `source_id` were given, or `kind` is not a known twin kind.
        """
        from rootcause.direct import KIND_RULES

        if dataset_id and source_id:
            raise InvalidArgumentError("Pass either dataset_id or source_id, not both")
        if not dataset_id and not source_id:
            raise InvalidArgumentError("A twin needs data: pass dataset_id= or source_id=")
        _guard.choice(kind, "kind", KIND_RULES)
        body: dict[str, Any] = {"name": name, "type": kind}
        if dataset_id:
            body["datasetId"] = dataset_id
        if source_id:
            body["sourceId"] = source_id
        if time_column:
            body["selectedTimeColumnName"] = time_column
        if environment_columns:
            body["environmentColumns"] = environment_columns
        if tags:
            body["tags"] = tags
        envelope = self._transport.request("POST", f"/api/v1/workspaces/{self.id}/digital-twins", json_body=body)
        doc = envelope.get("data", envelope)
        return Twin(self._transport, self.id, doc)

    def __repr__(self) -> str:
        return f"Workspace({self.name!r}, id={self.id})"

    def _repr_html_(self) -> str:
        counts = {
            "sources": len(self.sources),
            "datasets": len(self.datasets),
            "twins": len(self.twins),
        }
        rows = "".join(f"<tr><td>{key}</td><td>{value}</td></tr>" for key, value in counts.items())
        return f"<div><p><b>{self.name}</b></p><table>{rows}</table></div>"
