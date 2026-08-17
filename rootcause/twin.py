from pathlib import Path
from typing import TYPE_CHECKING, Any

from rootcause._http import Transport, poll_job, poll_run
from rootcause.errors import RootCauseError
from rootcause.graph import Graph
from rootcause.interventions import compile_do
from rootcause.results import ForecastResult, SampleDraws, ScoreResult, SimulationResult, UpdateResult

if TYPE_CHECKING:
    import pandas as pd

PANEL_KINDS = {"multi-environment-temporal", "multi-environment-static"}
TEMPORAL_KINDS = {"temporal", "multi-environment-temporal"}


class Twin:
    """A digital twin handle bound to one version (the latest unless told otherwise)."""

    def __init__(
        self,
        transport: Transport,
        workspace_id: str,
        doc: dict[str, Any],
        version_doc: dict[str, Any] | None = None,
    ) -> None:
        self._transport = transport
        self._workspace_id = workspace_id
        self.doc = doc
        self._version_doc = version_doc

    @property
    def id(self) -> str:
        return str(self.doc.get("id") or self.doc.get("_id"))

    @property
    def name(self) -> str:
        return str(self.doc.get("name", self.id))

    @property
    def kind(self) -> str:
        return str(self.doc.get("type", "static"))

    @property
    def is_panel(self) -> bool:
        return self.kind in PANEL_KINDS

    @property
    def is_temporal(self) -> bool:
        return self.kind in TEMPORAL_KINDS

    def _twin_path(self) -> str:
        return f"/api/v1/workspaces/{self._workspace_id}/digital-twins/{self.id}"

    @property
    def versions(self) -> list[dict[str, Any]]:
        envelope = self._transport.request("GET", f"{self._twin_path()}/versions")
        return list(envelope.get("data", []))

    @property
    def version(self) -> dict[str, Any]:
        if self._version_doc is None:
            versions = self.versions
            if not versions:
                raise RootCauseError(f'Twin "{self.name}" has no versions')
            self._version_doc = max(versions, key=lambda v: str(v.get("createdAt", "")))
        return self._version_doc

    @property
    def version_id(self) -> str:
        return str(self.version.get("id") or self.version.get("_id"))

    def at_version(self, version_id: str) -> "Twin":
        envelope = self._transport.request("GET", f"{self._twin_path()}/versions/{version_id}")
        return Twin(self._transport, self._workspace_id, self.doc, envelope.get("data", envelope))

    def _version_path(self) -> str:
        return f"{self._twin_path()}/versions/{self.version_id}"

    def _refresh_version(self) -> None:
        envelope = self._transport.request("GET", f"{self._twin_path()}/versions/{self.version_id}")
        self._version_doc = envelope.get("data", envelope)

    @property
    def source(self) -> "Any":
        """The raw source backing this version, or None when it trains off a dataset."""
        source_id = self.version.get("sourceId")
        if not source_id:
            return None
        from rootcause.workspace import Source

        envelope = self._transport.request("GET", f"/api/v1/workspaces/{self._workspace_id}/sources/{source_id}")
        return Source(self._transport, self._workspace_id, envelope.get("data", envelope))

    @property
    def graph(self) -> Graph:
        return Graph(self)

    def discover(self, *, webhook_url: str | None = None, timeout: float = 3600.0) -> Graph:
        """Run causal discovery on this version and return the discovered graph."""
        body = {"webhookUrl": webhook_url} if webhook_url else None
        envelope = self._transport.request("POST", f"{self._version_path()}/discover", json_body=body)
        job_id = str(envelope["data"]["jobId"])
        poll_job(self._transport, self._workspace_id, job_id, label=f"discover {self.name}", timeout=timeout)
        self._refresh_version()
        return self.graph

    def train(self, *, webhook_url: str | None = None, timeout: float = 7200.0) -> "Twin":
        """Train the model for this version, blocking until done.

        An already-trained version is returned as-is: the platform's lifecycle
        retrains through a new version, not by re-fitting in place. To rebuild
        a model from scratch (after an engine fix, or a corrupt artifact), use
        rc.discover(df, force=True) and train the fresh twin it returns.
        """
        import sys as _sys

        if str(self.version.get("lifecycleState", "")) == "trained":
            print(
                f'"{self.name}" is already trained; reusing the fitted model. '
                "Use rc.discover(df, force=True) to rebuild from scratch.",
                file=_sys.stderr,
            )
            return self
        body = {"webhookUrl": webhook_url} if webhook_url else None
        envelope = self._transport.request("POST", f"{self._version_path()}/train", json_body=body)
        job_id = str(envelope["data"]["jobId"])
        poll_job(self._transport, self._workspace_id, job_id, label=f"train {self.name}", timeout=timeout)
        self._refresh_version()
        return self

    def run_pipeline(self, *, webhook_url: str | None = None, timeout: float = 7200.0) -> "Twin":
        """Discovery + dependencies + roles + training in one pass."""
        body = {"webhookUrl": webhook_url} if webhook_url else None
        envelope = self._transport.request("POST", f"{self._version_path()}/run-pipeline", json_body=body)
        job_id = str(envelope["data"]["jobId"])
        poll_job(self._transport, self._workspace_id, job_id, label=f"pipeline {self.name}", timeout=timeout)
        self._refresh_version()
        return self

    def evaluate(self) -> dict[str, Any]:
        envelope = self._transport.request("GET", f"{self._version_path()}/evaluation")
        return envelope.get("data", envelope)

    def new_version(self, *, bump: str = "patch", base_version_id: str | None = None, dataset_id: str | None = None) -> "Twin":
        """Derive a fresh, untrained version from an existing one — the retrain primitive.

        Inherits the base version's configuration and causal graph, resets every
        training output, and returns the twin pinned to the new version.
        """
        body: dict[str, Any] = {"bump": bump}
        if base_version_id:
            body["baseVersionId"] = base_version_id
        if dataset_id:
            body["datasetId"] = dataset_id
        envelope = self._transport.request("POST", f"{self._twin_path()}/versions", json_body=body)
        doc = envelope.get("data", envelope)
        return self.at_version(str(doc.get("id") or doc.get("_id")))

    def retrain(self, *, bump: str = "patch", timeout: float = 7200.0) -> "Twin":
        """Create a new version off the latest and train it — the full retrain in one call."""
        fresh = self.new_version(bump=bump)
        return fresh.train(timeout=timeout)

    @property
    def update_eligibility(self) -> dict[str, Any]:
        """Whether update() would find new data, and whether it can assimilate incrementally."""
        envelope = self._transport.request("GET", f"{self._version_path()}/update-eligibility")
        return envelope.get("data", envelope)

    def update(self, *, webhook_url: str | None = None, timeout: float = 3600.0) -> UpdateResult:
        """Fold data added to the backing source since the last train/update into the model.

        No retrain: incremental assimilation. The job succeeds with a status
        rather than failing — `committed`, `up_to_date`, or `retrain_required`
        (the model can't take these rows incrementally; result.reasons says
        why — call retrain()). Static and temporal twins assimilate out of the
        box; panel twins need the v2 panel engine. Requires a trained version;
        extend or sync the source first so there is something new.
        """
        body: dict[str, Any] = {}
        if webhook_url:
            body["webhookUrl"] = webhook_url
        envelope = self._transport.request("POST", f"{self._version_path()}/update-model", json_body=body)
        job_id = str(envelope["data"]["jobId"])
        job = poll_job(self._transport, self._workspace_id, job_id, label=f"update {self.name}", timeout=timeout)
        self._refresh_version()
        return UpdateResult(job)

    @property
    def environments(self) -> "pd.DataFrame":
        """Panel twins: the environments in the version's data, with sample sizes."""
        import pandas as pd

        envelope = self._transport.request("GET", f"{self._version_path()}/environments")
        payload = envelope.get("data", envelope)
        rows = payload.get("environments", []) if isinstance(payload, dict) else []
        return pd.DataFrame(rows)

    def env(self, *environments: "str | dict[str, str]") -> "EnvSubset":
        """A handle pinned to a subset of this panel twin's environments.

        Pass environment names ("london"), envKeys ("store=london"), or exact
        {column: value} combos. Everything on the handle — graph, sample,
        intervene, forecast — is scoped to the subset.
        """
        if not environments:
            raise RootCauseError("Pass at least one environment, e.g. twin.env(\"london\", \"berlin\")")
        return EnvSubset(self, list(environments))

    def score(
        self,
        rows: "pd.DataFrame | list[dict[str, Any]]",
        targets: list[dict[str, Any]],
        *,
        max_changes: int = 3,
        constraints: dict[str, Any] | None = None,
        webhook_url: str | None = None,
        timeout: float = 3600.0,
    ) -> ScoreResult:
        """Score rows against target outcomes: each row gets its smallest flip.

        Static trained twins only. rows is a DataFrame or list of dicts whose
        keys name twin variables; targets is [{"variable": ..., "value": ...}].
        Blocks until the run completes and returns the ScoreResult.
        """
        if hasattr(rows, "to_dict"):
            rows = rows.to_dict(orient="records")  # type: ignore[union-attr]
        body: dict[str, Any] = {"rows": rows, "targets": targets, "maxChanges": max_changes}
        if constraints:
            body["constraints"] = constraints
        if webhook_url:
            body["webhookUrl"] = webhook_url
        envelope = self._transport.request("POST", f"{self._version_path()}/score", json_body=body)
        run_id = str(envelope["data"]["runId"])
        poll_run(self._transport, self._workspace_id, run_id, label=f"score {self.name}", timeout=timeout)
        return ScoreResult(self._transport, self._workspace_id, run_id)

    def sample(
        self,
        n: int = 1000,
        do: dict[str, Any] | None = None,
        where: Any = None,
        environments: list[str] | None = None,
        seed: int | None = None,
    ) -> SampleDraws:
        """Raw joint posterior draws — the primitive every simulation family wraps.

        do= applies interventions before sampling; where= scopes them to a
        subpopulation. Panel twins sample each environment independently
        (environments= narrows which) and derive stable per-environment child
        seeds from seed=.
        """
        interventions = compile_do(do, where) if do else []
        if self.is_panel:
            spec: dict[str, Any] = {
                "type": "panel_intervention",
                "interventions": interventions,
                "metrics": [],
                "environments": environments,
            }
        else:
            if environments is not None:
                raise RootCauseError(f'environments= only applies to panel twins; "{self.name}" is {self.kind}')
            spec = {"type": "intervention", "interventions": interventions, "metrics": []}
        envelope = self._transport.request(
            "POST",
            f"{self._version_path()}/sample",
            json_body={"spec": spec, "n": n, "seed": seed},
        )
        return SampleDraws(envelope.get("data", envelope))

    def intervene(
        self,
        do: dict[str, Any],
        where: Any = None,
        metrics: list[dict[str, Any]] | None = None,
        outcomes: list[str] | None = None,
        environments: list[str] | None = None,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        """Run an intervention simulation and block for the result.

        Interventions measure their effect through metrics: pass metrics=[rc.metric(...)]
        for full control, or outcomes=["revenue"] for mean-of-column metrics. For raw
        effect distributions without metrics, use twin.sample(do=...).
        """
        if metrics is None:
            if not outcomes:
                raise RootCauseError(
                    "Interventions need at least one metric. Pass outcomes=['revenue'] for "
                    "mean-of-column metrics, metrics=[rc.metric(...)] for custom SQL, or use "
                    "twin.sample(do=...) for raw draws."
                )
            from rootcause.interventions import mean_metrics

            metrics = mean_metrics(outcomes)
        interventions = compile_do(do, where)
        if self.is_panel:
            scenario: dict[str, Any] = {
                "type": "panel_intervention",
                "interventions": interventions,
                "metrics": metrics or [],
                "environments": environments,
            }
        elif self.is_temporal:
            scenario = {"type": "temporal_intervention", "interventions": interventions, "metrics": metrics or []}
        else:
            scenario = {"type": "intervention", "interventions": interventions, "metrics": metrics or []}
        return self._run_scenario(scenario, timeout=timeout)

    def forecast(
        self,
        horizon: int,
        targets: list[str] | None = None,
        environments: list[str] | None = None,
        confidence: float = 0.95,
        origin_timestamp: int | None = None,
        aggregate: str | None = None,
        *,
        timeout: float = 3600.0,
    ) -> ForecastResult:
        """Forecast `horizon` steps ahead for the target variables.

        Panel twins forecast each environment; environments= narrows which, and
        aggregate= ("sum", "avg", "min", "max") adds a combined series across
        them. origin_timestamp (ms epoch) anchors the forecast start, which is
        how backtests align a forecast against data the twin never saw.
        """
        if not self.is_temporal:
            raise RootCauseError(
                f'"{self.name}" is a {self.kind} twin; forecasting needs a temporal or panel-temporal twin'
            )
        if aggregate is not None and not self.is_panel:
            raise RootCauseError(f'aggregate= only applies to panel twins; "{self.name}" is {self.kind}')
        resolved_targets = targets or self._infer_targets()
        scenario: dict[str, Any] = {
            "type": "panel_forecast" if self.is_panel else "forecast",
            "forecastH": int(horizon),
            "targetVars": resolved_targets,
            "confidenceLevel": confidence,
            "originTimestamp": origin_timestamp,
        }
        if self.is_panel:
            scenario["environments"] = environments
            scenario["aggregateMode"] = aggregate
        result = self._run_scenario(scenario, timeout=timeout)
        return ForecastResult(self._transport, self._workspace_id, result.run_id, result.run, scenario)

    def ask(self, query: str, *, timeout: float = 3600.0) -> SimulationResult:
        """Natural-language question → generated scenario → executed simulation."""
        envelope = self._transport.request(
            "POST", f"{self._version_path()}/scenario-from-query", json_body={"query": query}
        )
        data = envelope.get("data", envelope)
        scenario = data.get("scenario") if isinstance(data, dict) else None
        if not isinstance(scenario, dict):
            raise RootCauseError(f"Could not generate a scenario from that question; response: {data}")
        return self._run_scenario(scenario, timeout=timeout)

    def console(self, *, height: int = 560, theme: str = ""):
        """The interactive causal-graph console under the cell: the same app Claude renders.

        Explore edges, type intervention values, and re-run scenarios; every
        control round-trips live through the platform's MCP gateway with this
        session's credentials. Needs: pip install "rootcause-sdk[jupyter]".
        """
        from rootcause.jupyter import app

        return app(
            "query_causal_graph",
            {
                "workspaceId": self._workspace_id,
                "digitalTwinVersionId": self.version_id,
                "queryType": "graph",
            },
            height=height,
            theme=theme,
            transport=self._transport,
        )

    def save(self, path: str | Path, *, include_runs: bool = False, timeout: float = 3600.0) -> Path:
        """Export this twin (trained params included) as a portable .rctwin zip."""
        envelope = self._transport.request(
            "POST", f"{self._twin_path()}/export", json_body={"includeRuns": include_runs}
        )
        job_id = str(envelope["data"]["jobId"])
        poll_job(self._transport, self._workspace_id, job_id, label=f"export {self.name}", timeout=timeout)
        blob = self._transport.request_bytes("GET", f"{self._twin_path()}/export/{job_id}/download")
        target = Path(path)
        target.write_bytes(blob)
        return target

    def _run_scenario(self, scenario: dict[str, Any], *, timeout: float) -> SimulationResult:
        envelope = self._transport.request(
            "POST",
            f"/api/v1/workspaces/{self._workspace_id}/simulations",
            json_body={
                "digitalTwinId": self.id,
                "digitalTwinVersionId": self.version_id,
                "scenario": scenario,
            },
        )
        run_id = str(envelope["data"]["runId"])
        label = str(scenario.get("type", "simulation"))
        run_doc = poll_run(self._transport, self._workspace_id, run_id, label=label, timeout=timeout)
        return SimulationResult(self._transport, self._workspace_id, run_id, run_doc, scenario)

    def _infer_targets(self) -> list[str]:
        envelope = self._transport.request("GET", f"{self._version_path()}/variable-roles")
        roles = envelope.get("data", envelope)
        if isinstance(roles, dict):
            targets = [
                variable
                for variable, role in roles.items()
                if isinstance(role, str) and role.lower() in {"target", "output", "outcome"}
            ]
            if targets:
                return targets
        raise RootCauseError(
            "Could not infer target variables from the version's variable roles; pass targets=[...]"
        )

    def __repr__(self) -> str:
        state = self.version.get("lifecycleState", "unknown") if self._version_doc else "…"
        return f"Twin({self.name!r}, kind={self.kind}, version={self.version_id}, state={state})"

    def _repr_html_(self) -> str:
        version = self.version
        rows = "".join(
            f"<tr><td>{label}</td><td>{value}</td></tr>"
            for label, value in [
                ("kind", self.kind),
                ("version", self.version_id),
                ("state", version.get("lifecycleState", "unknown")),
            ]
        )
        return f"<div><p><b>{self.name}</b></p><table>{rows}</table></div>"


class EnvSubset:
    """A panel twin pinned to a subset of its environments.

    Everything on the handle runs scoped to the subset: `graph` re-aggregates
    the causal adjacency over just these environments, and sample/intervene/
    forecast delegate to the twin with environments= filled in.
    """

    def __init__(self, twin: Twin, environments: list["str | dict[str, str]"]) -> None:
        self.twin = twin
        self._requested = environments

    def _listing(self) -> dict[str, Any]:
        envelope = self.twin._transport.request("GET", f"{self.twin._version_path()}/environments")
        payload = envelope.get("data", envelope)
        return payload if isinstance(payload, dict) else {}

    def combos(self) -> list[dict[str, str]]:
        """The subset as exact {column: value} combos, resolved against the twin's environments.

        The listing carries each environment's values as a list ordered by
        environmentColumns; zipping the two recovers the combo.
        """
        payload: dict[str, Any] | None = None
        resolved: list[dict[str, str]] = []
        for item in self._requested:
            if isinstance(item, dict):
                resolved.append({str(k): str(v) for k, v in item.items()})
                continue
            if payload is None:
                payload = self._listing()
            columns = [str(c) for c in (payload.get("environmentColumns") or [])]
            envs = list(payload.get("environments") or [])
            match = next(
                (e for e in envs
                 if item == e.get("envKey") or item in [str(v) for v in (e.get("values") or [])]),
                None,
            )
            if match is None:
                known = ", ".join(str(e.get("envKey")) for e in envs[:8])
                raise RootCauseError(f'Environment "{item}" not found on "{self.twin.name}" (known: {known}…)')
            values = [str(v) for v in (match.get("values") or [])]
            if not columns or len(columns) != len(values):
                raise RootCauseError(
                    f'Could not resolve "{item}" to a column combo; pass it as '
                    f'{{column: value}} instead (environment columns: {columns})'
                )
            resolved.append(dict(zip(columns, values)))
        return resolved

    def _names(self) -> list[str]:
        names: list[str] = []
        for item in self._requested:
            if isinstance(item, dict):
                if len(item) != 1:
                    raise RootCauseError(
                        "Simulations on a multi-column environment subset need string names; "
                        "pass the envKey strings instead of dicts"
                    )
                names.append(str(next(iter(item.values()))))
            else:
                names.append(item)
        return names

    def adjacency(self, agreement_threshold: float | None = None) -> "pd.DataFrame":
        """The causal adjacency aggregated over just this subset of environments.

        Returns the edges as a DataFrame (source, target, strength, agreementRate, …);
        frame.attrs carries envCount, sampleSize, totalEnvCount, and the threshold.
        """
        import pandas as pd

        body: dict[str, Any] = {"mode": "environments", "environments": self.combos()}
        if agreement_threshold is not None:
            body["agreementThreshold"] = agreement_threshold
        envelope = self.twin._transport.request(
            "POST", f"{self.twin._version_path()}/graph/slice", json_body=body
        )
        data = envelope.get("data", envelope)
        frame = pd.DataFrame(data.get("causalGraph", []))
        for key in ("envCount", "sampleSize", "totalEnvCount", "unresolvedEnvCount", "agreementThreshold"):
            if key in data:
                frame.attrs[key] = data[key]
        return frame

    @property
    def graph(self) -> "pd.DataFrame":
        return self.adjacency()

    def sample(self, n: int = 1000, do: dict[str, Any] | None = None, where: Any = None, seed: int | None = None) -> SampleDraws:
        return self.twin.sample(n=n, do=do, where=where, environments=self._names(), seed=seed)

    def intervene(
        self,
        do: dict[str, Any],
        where: Any = None,
        metrics: list[dict[str, Any]] | None = None,
        outcomes: list[str] | None = None,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        return self.twin.intervene(
            do, where=where, metrics=metrics, outcomes=outcomes, environments=self._names(), timeout=timeout
        )

    def forecast(
        self,
        horizon: int,
        targets: list[str] | None = None,
        confidence: float = 0.95,
        origin_timestamp: int | None = None,
        aggregate: str | None = None,
        *,
        timeout: float = 3600.0,
    ) -> ForecastResult:
        return self.twin.forecast(
            horizon,
            targets=targets,
            environments=self._names(),
            confidence=confidence,
            origin_timestamp=origin_timestamp,
            aggregate=aggregate,
            timeout=timeout,
        )

    def __repr__(self) -> str:
        labels = ", ".join(
            "/".join(item.values()) if isinstance(item, dict) else str(item) for item in self._requested
        )
        return f"EnvSubset({self.twin.name!r}, environments=[{labels}])"
