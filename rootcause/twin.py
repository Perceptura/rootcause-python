from pathlib import Path
from typing import TYPE_CHECKING, Any

from rootcause._http import Transport, poll_job, poll_run
from rootcause.errors import RootCauseError
from rootcause.graph import Graph
from rootcause.interventions import compile_do
from rootcause.results import ForecastResult, SampleDraws, SimulationResult

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
    def graph(self) -> Graph:
        return Graph(self)

    def discover(self, *, timeout: float = 3600.0) -> Graph:
        """Run causal discovery on this version and return the discovered graph."""
        envelope = self._transport.request("POST", f"{self._version_path()}/discover")
        job_id = str(envelope["data"]["jobId"])
        poll_job(self._transport, self._workspace_id, job_id, label=f"discover {self.name}", timeout=timeout)
        self._refresh_version()
        return self.graph

    def train(self, *, timeout: float = 7200.0) -> "Twin":
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
        envelope = self._transport.request("POST", f"{self._version_path()}/train")
        job_id = str(envelope["data"]["jobId"])
        poll_job(self._transport, self._workspace_id, job_id, label=f"train {self.name}", timeout=timeout)
        self._refresh_version()
        return self

    def run_pipeline(self, *, timeout: float = 7200.0) -> "Twin":
        """Discovery + dependencies + roles + training in one pass."""
        envelope = self._transport.request("POST", f"{self._version_path()}/run-pipeline")
        job_id = str(envelope["data"]["jobId"])
        poll_job(self._transport, self._workspace_id, job_id, label=f"pipeline {self.name}", timeout=timeout)
        self._refresh_version()
        return self

    def evaluate(self) -> dict[str, Any]:
        envelope = self._transport.request("GET", f"{self._version_path()}/evaluation")
        return envelope.get("data", envelope)

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
        *,
        timeout: float = 3600.0,
    ) -> ForecastResult:
        """Forecast `horizon` steps ahead for the target variables."""
        if not self.is_temporal:
            raise RootCauseError(
                f'"{self.name}" is a {self.kind} twin; forecasting needs a temporal or panel-temporal twin'
            )
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
