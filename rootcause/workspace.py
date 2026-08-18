import difflib
import io
import time
from typing import TYPE_CHECKING, Any, Callable, Iterator

from rootcause._http import Transport, poll_job
from rootcause.errors import NotFoundInWorkspaceError, RootCauseError
from rootcause.ontology import Ontology
from rootcause.twin import Twin

if TYPE_CHECKING:
    import pandas as pd


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

    @property
    def id(self) -> str:
        return str(self.doc.get("id") or self.doc.get("_id"))

    @property
    def name(self) -> str:
        return str(self.doc.get("name", self.id))

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
        import pandas as pd

        blob = self._transport.request_bytes("GET", f"{self._path()}/export/parquet")
        return pd.read_parquet(io.BytesIO(blob))

    def extend(self, frame: "pd.DataFrame") -> None:
        """Append new rows to this source. Blocks until the rows are ingested."""
        buffer = io.BytesIO()
        frame.to_parquet(buffer, index=False)
        self._transport.request(
            "POST",
            f"{self._path()}/extend",
            content=buffer.getvalue(),
            headers={"Content-Type": "application/octet-stream", "x-filename": f"{self.name}-extend.parquet"},
        )

    def __repr__(self) -> str:
        return f"Source({self.name!r}, id={self.id})"


class DataView:
    """A derived, queryable dataset built from one or more sources."""

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
        import pandas as pd

        blob = self._transport.request_bytes("GET", f"{self._path()}/export/parquet")
        return pd.read_parquet(io.BytesIO(blob))

    def records(self, limit: int = 100, cursor: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        envelope = self._transport.request("GET", f"{self._path()}/records", params=params)
        return list(envelope.get("data", []))

    def __repr__(self) -> str:
        return f"DataView({self.name!r}, id={self.id})"


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
        envelope = self._transport.request(
            "GET", f"/api/v1/connectors/{self.id}/browse", params={"level": level, **context}
        )
        return envelope.get("data", envelope)

    def query(self, query: str, *, limit: int = 100, **config: Any) -> "pd.DataFrame":
        """Run a custom query against the external system and return sample rows.

        The authoring loop for custom SQL: nothing is stored, database errors
        come back verbatim. Extra kwargs (database=, warehouse=, schema=, …)
        join the connector config.
        """
        import pandas as pd

        envelope = self._transport.request(
            "POST",
            f"/api/v1/connectors/{self.id}/preview-query",
            json_body={"config": {"query": query, **config}, "limit": limit},
        )
        data = envelope.get("data", envelope)
        if not data.get("success", False):
            raise RootCauseError(f"Query preview failed: {data.get('error', 'unknown error')}")
        columns = [c["name"] for c in data.get("columns", [])]
        return pd.DataFrame(data.get("rows", []), columns=columns)

    def import_table(self, table: str, *, name: str | None = None, timeout: float = 3600.0, **config: Any) -> Source:
        """Import one table into the workspace as a new source."""
        return self.run_import({"table": table, **config}, dataset_name=name, timeout=timeout)

    def import_query(self, query: str, *, name: str | None = None, timeout: float = 3600.0, **config: Any) -> Source:
        """Import the result of a custom query into the workspace as a new source."""
        return self.run_import({"query": query, **config}, dataset_name=name, timeout=timeout)

    def run_import(self, config: dict[str, Any], *, dataset_name: str | None = None, timeout: float = 3600.0) -> Source:
        body: dict[str, Any] = {"workspaceId": self._workspace_id, "config": config}
        if dataset_name:
            body["datasetName"] = dataset_name
        envelope = self._transport.request(
            "POST",
            f"/api/v1/connectors/{self.id}/import",
            json_body=body,
        )
        job_id = str(envelope["data"]["jobId"])
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
        collection = _Collection(lambda: self._list("/datasets"), lambda doc: DataView(self._transport, self.id, doc))
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
        """Register a connector to an external system (credentials are stored encrypted)."""
        envelope = self._transport.request(
            "POST",
            "/api/v1/connectors",
            json_body={"name": name, "type": type, "credentials": {"type": type, **credentials} if credentials else None},
        )
        doc = envelope.get("data", envelope)
        return Connector(self._transport, self.id, doc)

    def dataset(self, needle: str) -> DataView:
        return self.datasets[needle]

    def source(self, needle: str) -> Source:
        return self.sources[needle]

    def twin(self, needle: str) -> Twin:
        return self.twins[needle]

    def upload(self, frame: "pd.DataFrame", name: str, *, wait: bool = True, timeout: float = 600.0) -> Source:
        """Upload a DataFrame as a new source (parquet on the wire, full ingest server-side)."""
        buffer = io.BytesIO()
        frame.to_parquet(buffer, index=False)

        created = self._transport.request(
            "POST", f"/api/v1/workspaces/{self.id}/sources", json_body={"name": name}
        )
        doc = created.get("data", created)
        source = Source(self._transport, self.id, doc)

        self._transport.request(
            "POST",
            f"/api/v1/workspaces/{self.id}/sources/{source.id}/upload",
            content=buffer.getvalue(),
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
        if dataset_id and source_id:
            raise RootCauseError("Pass either dataset_id or source_id, not both")
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
