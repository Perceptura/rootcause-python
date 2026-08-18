"""Return types for the twin's verbs; each one flattens to a DataFrame."""

from rootcause.errors import RootCauseError
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

    from rootcause._http import Transport


def _pandas():
    import pandas as pd

    return pd


class SampleDraws:
    """Raw joint posterior draws from twin.sample(), columnar on the wire."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.raw = payload
        self.n = int(payload.get("n", 0))

    @property
    def environments(self) -> list[str]:
        return list(self.raw.get("environments", {}).keys())

    def to_frame(self) -> "pd.DataFrame":
        pd = _pandas()
        if "environments" in self.raw:
            frames = []
            for env, columns in self.raw["environments"].items():
                frame = pd.DataFrame(columns)
                frame.insert(0, "environment", env)
                frames.append(frame)
            return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        return pd.DataFrame(self.raw.get("columns", {}))

    def __repr__(self) -> str:
        envs = f", environments={len(self.environments)}" if "environments" in self.raw else ""
        return f"SampleDraws(n={self.n}{envs})"

    def _repr_html_(self) -> str:
        return self.to_frame().head(20)._repr_html_()


def _walk_records(node: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], list[dict[str, Any]]]]:
    found: list[tuple[tuple[str, ...], list[dict[str, Any]]]] = []
    if isinstance(node, list) and node and all(isinstance(item, dict) for item in node):
        found.append((path, node))
    elif isinstance(node, dict):
        for key, value in node.items():
            found.extend(_walk_records(value, (*path, str(key))))
    return found


class SimulationResult:
    """A completed simulation run: raw outputs plus best-effort tabular and narrative views."""

    def __init__(
        self,
        transport: "Transport",
        workspace_id: str,
        run_id: str,
        run_doc: dict[str, Any],
        scenario: dict[str, Any] | None = None,
    ) -> None:
        self._transport = transport
        self._workspace_id = workspace_id
        self.run_id = run_id
        self.run = run_doc
        self.scenario = scenario
        self._results: Any = None
        self._summary: str | None = None

    @property
    def results(self) -> Any:
        if self._results is None:
            envelope = self._transport.request(
                "GET", f"/api/v1/workspaces/{self._workspace_id}/simulations/{self.run_id}/results"
            )
            self._results = envelope.get("data", envelope)
        return self._results

    @property
    def summary(self) -> str:
        if self._summary is None:
            envelope = self._transport.request(
                "GET", f"/api/v1/workspaces/{self._workspace_id}/simulations/{self.run_id}/summary"
            )
            data = envelope.get("data", envelope)
            self._summary = data if isinstance(data, str) else str(
                data.get("summary") or data.get("narrative") or data
            )
        return self._summary

    def to_frame(self, path: str | None = None) -> "pd.DataFrame":
        """Tabularize the result payload.

        Simulation families answer with different shapes; this finds record
        lists in the payload. With several candidates, pass path="a.b" to pick
        one — the error message lists what is available.
        """
        pd = _pandas()
        candidates = _walk_records(self.results)
        if not candidates:
            raise ValueError(
                "No tabular records found in this result; inspect .results for the raw payload"
            )
        if path is not None:
            wanted = tuple(path.split("."))
            for candidate_path, records in candidates:
                if candidate_path == wanted:
                    return pd.DataFrame(records)
            raise ValueError(
                f'No records at "{path}". Available: {", ".join(".".join(p) for p, _ in candidates)}'
            )
        if len(candidates) == 1:
            return pd.DataFrame(candidates[0][1])
        largest = max(candidates, key=lambda item: len(item[1]))
        return pd.DataFrame(largest[1])

    @property
    def tables(self) -> list[str]:
        return [".".join(path) for path, _ in _walk_records(self.results)]

    def export(self, fmt: str = "csv") -> bytes:
        return self._transport.request_bytes(
            "GET", f"/api/v1/workspaces/{self._workspace_id}/simulations/{self.run_id}/export/{fmt}"
        )

    def sweep(self, metric: str | None = None) -> "pd.DataFrame":
        """Full dose-response curve of a range intervention, one metric at a time.

        With metric=None and several metrics on the run, raises with the list of
        available metric names.
        """
        pd = _pandas()
        params = {"metric": metric} if metric else {}
        envelope = self._transport.request(
            "GET",
            f"/api/v1/workspaces/{self._workspace_id}/simulations/{self.run_id}/sweep",
            params=params,
        )
        payload = envelope.get("data", envelope)
        if metric is None:
            metrics = payload.get("metrics") or []
            if len(metrics) == 1:
                return self.sweep(metrics[0])
            raise RootCauseError(
                f"This sweep carries {len(metrics)} metrics; pass metric= one of: {', '.join(metrics)}"
            )
        frame = pd.DataFrame(payload.get("points") or [])
        frame.attrs["metric"] = payload.get("metric")
        frame.attrs["sweptVariable"] = payload.get("sweptVariable")
        return frame

    def __repr__(self) -> str:
        scenario_type = (self.scenario or {}).get("type") or self.run.get("scenarioType") or "simulation"
        return f"SimulationResult({scenario_type}, run={self.run_id}, status={self.run.get('status')})"

    def _repr_html_(self) -> str:
        try:
            head = self.to_frame().head(15)._repr_html_()
        except (ValueError, ImportError):
            head = ""
        return f"<div><p><b>{self!r}</b></p>{head}</div>"


class ForecastResult(SimulationResult):
    """Forecast run with a tidy long-format frame: environment, series, timestamp, values."""

    @staticmethod
    def _env_results(results: Any) -> tuple[dict[str, Any] | None, Any]:
        if not isinstance(results, dict):
            return None, None
        if "environmentResults" in results:
            return results.get("environmentResults"), results.get("aggregateResult")
        for value in results.values():
            if isinstance(value, dict) and "environmentResults" in value:
                return value.get("environmentResults"), value.get("aggregateResult")
        return None, None

    def to_frame(self, path: str | None = None) -> "pd.DataFrame":
        pd = _pandas()
        if path is not None:
            return super().to_frame(path)
        env_results, aggregate = self._env_results(self.results)
        if isinstance(env_results, dict) and env_results:
            frames = []
            for env, env_payload in [*env_results.items(), *([("aggregate", aggregate)] if aggregate else [])]:
                records = _walk_records(env_payload)
                if records:
                    frame = pd.DataFrame(max(records, key=lambda item: len(item[1]))[1])
                    frame.insert(0, "environment", env)
                    frames.append(frame)
            if frames:
                return pd.concat(frames, ignore_index=True)
        return super().to_frame()


class UpdateResult:
    """Outcome of an incremental model update (assimilation)."""

    def __init__(self, job: dict[str, Any]) -> None:
        self.job = job
        # The assimilation outcome rides on the run's metadata; `result` stays null.
        outcome = {**(job.get("result") or {}), **(job.get("metadata") or {})}
        self.status = str(outcome.get("status") or job.get("status") or "unknown")
        self.rows_assimilated = outcome.get("rowsAssimilated")
        self.reasons = list(outcome.get("reasons") or [])

    @property
    def retrain_required(self) -> bool:
        return self.status == "retrain_required"

    def __repr__(self) -> str:
        rows = f", rows={self.rows_assimilated}" if self.rows_assimilated is not None else ""
        why = f", reasons={self.reasons[0]!r}" if self.retrain_required and self.reasons else ""
        return f"UpdateResult(status={self.status!r}{rows}{why})"


class ScoreResult:
    """Verdicts and per-row counterfactual changes from a batch scoring run."""

    def __init__(self, transport: Any, workspace_id: str, run_id: str) -> None:
        self._transport = transport
        self._workspace_id = workspace_id
        self.run_id = run_id
        self._first_page: dict[str, Any] | None = None

    def _page(self, cursor: str | None = None, limit: int = 100) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._transport.request(
            "GET",
            f"/api/v1/workspaces/{self._workspace_id}/simulations/{self.run_id}/score",
            params=params,
        )

    @property
    def digest(self) -> dict[str, Any]:
        """Verdict counts, top drivers, and the first row summaries."""
        if self._first_page is None:
            self._first_page = self._page()
        return dict((self._first_page.get("data") or {}).get("digest") or {})

    def to_frame(self, max_rows: int | None = None) -> "pd.DataFrame":
        """Every scored row with its full change list, paged transparently."""
        pd = _pandas()
        if self._first_page is None:
            self._first_page = self._page()
        page = self._first_page
        rows = list((page.get("data") or {}).get("rows") or [])
        cursor = (page.get("pagination") or {}).get("cursor")
        while cursor and (max_rows is None or len(rows) < max_rows):
            page = self._page(cursor)
            rows.extend((page.get("data") or {}).get("rows") or [])
            cursor = (page.get("pagination") or {}).get("cursor")
        if max_rows is not None:
            rows = rows[:max_rows]
        return pd.json_normalize(rows)

    def __repr__(self) -> str:
        verdicts = self.digest.get("verdictCounts") or {}
        summary = ", ".join(f"{key}={value}" for key, value in verdicts.items() if value)
        return f"ScoreResult(run={self.run_id}, {summary or 'no verdicts'})"
