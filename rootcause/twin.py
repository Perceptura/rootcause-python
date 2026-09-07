"""The digital twin handle: train, predict, simulate, explain, diagnose, optimise, export."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rootcause import _guard
from rootcause._http import Transport, expect, poll_job, poll_run
from rootcause.errors import InvalidArgumentError, RootCauseApiError, RootCauseError
from rootcause.graph import Graph
from rootcause.interventions import compile_do
from rootcause.results import (
    ForecastResult,
    PredictionResult,
    SampleDraws,
    ScoreResult,
    SimulationResult,
    UpdateResult,
)

if TYPE_CHECKING:
    import pandas as pd

PANEL_KINDS = {"multi-environment-temporal", "multi-environment-static"}
TEMPORAL_KINDS = {"temporal", "multi-environment-temporal"}
PREDICT_KINDS = {"static", "multi-environment-static"}
AGGREGATES = {"sum", "avg", "min", "max"}
BUMPS = {"patch", "minor", "major"}
EXPLANATION_MODES = {"directional", "discovery", "impact"}

# One scenario family, one name per twin kind: the platform spells the same
# question differently depending on what the twin is, and picking the wrong
# spelling is a 422 rather than a wrong answer.
EXPLANATION_TYPES = {
    "static": "explanation",
    "temporal": "temporal_explanation",
    "multi-environment-static": "panel_explanation",
    "multi-environment-temporal": "panel_explanation",
}
OPTIMISATION_TYPES = {
    "static": "optimisation",
    "temporal": "temporal_optimisation",
    "multi-environment-static": "panel_optimisation",
    "multi-environment-temporal": "panel_optimisation",
}
ROOT_CAUSE_TYPES = {
    "static": "root_cause_analysis",
    "temporal": "temporal_root_cause_analysis",
    "multi-environment-static": "static_panel_root_cause_analysis",
    "multi-environment-temporal": "panel_root_cause_analysis",
}
ANOMALY_TYPES = {
    "static": "anomaly_detection",
    "temporal": "temporal_anomaly_detection",
    "multi-environment-static": "static_panel_anomaly_detection",
    "multi-environment-temporal": "panel_anomaly_detection",
}


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

    def delete(self) -> None:
        """Delete this twin permanently: models, versions, runs and record.

        Running discovery or simulation workflows are cancelled first. There is
        no undo — the platform's own delete confirmation exists for a reason.
        Requires the `digital-twins:delete` scope.
        """
        self._transport.request("DELETE", self._twin_path())

    def link(self) -> "Any":
        """This twin version's page on the platform, as a clickable URL."""
        from rootcause._links import workspace_link

        label = str(self.version.get("version") or "")
        suffix = f"?version={label}" if label else ""
        return workspace_link(self._transport, self._workspace_id, f"/twins/{self.id}{suffix}")

    def discover(self, *, webhook_url: str | None = None, timeout: float = 3600.0) -> Graph:
        """Run causal discovery on this version and return the discovered graph.

        Args:
            webhook_url: Called with the job result instead of waiting on it.
            timeout: Seconds to wait for the discovery job.

        Returns:
            The discovered [`Graph`](#graph).
        """
        body = {"webhookUrl": webhook_url} if webhook_url else None
        envelope = self._transport.request("POST", f"{self._version_path()}/discover", json_body=body)
        job_id = expect(envelope, "jobId", "discovery job")
        poll_job(self._transport, self._workspace_id, job_id, label=f"discover {self.name}", timeout=timeout)
        self._refresh_version()
        return self.graph

    def train(self, *, webhook_url: str | None = None, timeout: float = 7200.0) -> "Twin":
        """Train the model for this version, blocking until done.

        An already-trained version is returned as-is: the platform's lifecycle
        retrains through a new version, not by re-fitting in place. To rebuild
        a model from scratch (after an engine fix, or a corrupt artifact), use
        rc.discover(df, force=True) and train the fresh twin it returns.

        Args:
            webhook_url: Called with the job result instead of waiting on it.
            timeout: Seconds to wait for the training job.

        Returns:
            This twin, trained. An already-trained version comes back unchanged.
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
        job_id = expect(envelope, "jobId", "training job")
        poll_job(self._transport, self._workspace_id, job_id, label=f"train {self.name}", timeout=timeout)
        self._refresh_version()
        return self

    def run_pipeline(self, *, webhook_url: str | None = None, timeout: float = 7200.0) -> "Twin":
        """Discovery + dependencies + roles + training in one pass.

        Args:
            webhook_url: Called with the job result instead of waiting on it.
            timeout: Seconds to wait for the whole pipeline.

        Returns:
            This twin, trained.
        """
        body = {"webhookUrl": webhook_url} if webhook_url else None
        envelope = self._transport.request("POST", f"{self._version_path()}/run-pipeline", json_body=body)
        job_id = expect(envelope, "jobId", "pipeline job")
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

        Args:
            bump: Which part of the version number to advance: `patch`, `minor`,
                or `major`.
            base_version_id: Version to derive from. Defaults to the latest.
            dataset_id: Train the new version off a different dataset.

        Returns:
            A handle bound to the new, untrained version.
        """
        body: dict[str, Any] = {"bump": _guard.choice(bump, "bump", BUMPS)}
        if base_version_id:
            body["baseVersionId"] = base_version_id
        if dataset_id:
            body["datasetId"] = dataset_id
        envelope = self._transport.request("POST", f"{self._twin_path()}/versions", json_body=body)
        doc = envelope.get("data", envelope)
        return self.at_version(str(doc.get("id") or doc.get("_id")))

    def retrain(self, *, bump: str = "patch", timeout: float = 7200.0) -> "Twin":
        """Create a new version off the latest and train it — the full retrain in one call.

        Args:
            bump: Which part of the version number to advance: `patch`, `minor`,
                or `major`.
            timeout: Seconds to wait for the training job.

        Returns:
            A handle bound to the newly trained version.
        """
        fresh = self.new_version(bump=bump)
        return fresh.train(timeout=timeout)

    @property
    def roles(self) -> dict[str, Any]:
        """The version's variable roles: which variables are sources and which are targets.

        Falls back to the platform's suggested roles when none have been set.

        Returns:
            `{"sources": [...], "targets": [...]}`.
        """
        envelope = self._transport.request("GET", f"{self._version_path()}/variable-roles")
        return envelope.get("data", envelope)

    def set_roles(self, *, targets: list[str] | None = None, sources: list[str] | None = None) -> dict[str, Any]:
        """Set the version's variable roles ahead of discovery and training.

        Roles steer the causal engine: targets are the outcomes the model is
        for, sources are the levers. Pass either list to change just that
        side — the other keeps its current (or suggested) value. This is the
        per-version counterpart of the ontology-level
        `concept.override(suggested_role=...)`, which sets the default for
        every future twin built over that concept.

        Args:
            targets: Outcome variables.
            sources: Driver variables.

        Returns:
            The stored roles document.
        """
        if targets is None and sources is None:
            raise RootCauseError("Pass targets=, sources=, or both")
        current = self.roles if (targets is None or sources is None) else {}
        known = {str(f.get("field")) for f in (self.version.get("inputFields") or []) if f.get("field")}
        wanted = [*(targets or []), *(sources or [])]
        unknown = [v for v in wanted if known and v not in known]
        if unknown:
            raise RootCauseError(
                f"Unknown variable(s) {unknown}; this version's variables: {sorted(known)}"
            )
        body = {
            "sources": sources if sources is not None else list(current.get("sources") or []),
            "targets": targets if targets is not None else list(current.get("targets") or []),
        }
        envelope = self._transport.request("PUT", f"{self._version_path()}/variable-roles", json_body=body)
        self._refresh_version()
        return envelope.get("data", envelope)

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

        Args:
            webhook_url: Called with the job result instead of waiting on it.
            timeout: Seconds to wait for the update job.

        Returns:
            An [`UpdateResult`](#updateresult). Never raises on
            `retrain_required`.
        """
        body: dict[str, Any] = {}
        if webhook_url:
            body["webhookUrl"] = webhook_url
        envelope = self._transport.request("POST", f"{self._version_path()}/update-model", json_body=body)
        job_id = expect(envelope, "jobId", "update job")
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

    def env(
        self,
        *environments: "str | dict[str, str]",
        where: "list[tuple] | dict[str, Any] | None" = None,
    ) -> "EnvSubset":
        """A handle pinned to a subset of this panel twin's environments.

        Name them directly — environment names ("london"), envKeys, or exact
        {column: value} combos — or select them by data with where=, filtering
        on any twin column through per-environment statistics:

        ```python
        twin.env("london", "berlin")                       # by name
        twin.env(where=[("revenue", "avg", ">", 400)])     # by aggregate
        twin.env(where=[("region", "==", "EMEA"),          # constant column
                        ("demand", "min", ">=", 0)])       # AND of filters
        ```

        Everything on the handle — graph, environments, sample, intervene,
        forecast — is scoped to the subset.

        Args:
            *environments: Environment names, envKeys, or `{column: value}`
                combos.
            where: Stat filters instead of names — tuples of
                `(column, op, value)` for constant-per-environment columns, or
                `(column, reduce, op, value)` with reduce one of `avg`/`mean`,
                `min`, `max`, or `any` (at least one matching row). A dict
                filter group passes through as written.

        Returns:
            An [`EnvSubset`](#envsubset) pinned to those environments.

        Raises:
            RootCauseError: Neither (or both) selection styles were passed.
        """
        if environments and where is not None:
            raise RootCauseError("Pass environments or where=, not both")
        if where is not None:
            return EnvSubset(self, [], stat_filters=_compile_env_where(where))
        if not environments:
            raise RootCauseError(
                'Pass at least one environment (twin.env("london")) or a where= filter'
            )
        return EnvSubset(self, list(environments))

    @property
    def groups(self) -> "list[Group]":
        """The twin's saved environment groups — the same ones the platform's picker lists.

        Groups belong to the twin rather than to a version, so they survive
        retraining; each one's membership is resolved against this handle's
        version when you touch it.
        """
        envelope = self._transport.request("GET", f"{self._twin_path()}/environment-groups")
        docs = envelope.get("data", envelope)
        return [Group(self, doc) for doc in docs] if isinstance(docs, list) else []

    def group(self, name_or_id: str) -> "Group":
        """One saved environment group, by name or id.

        Args:
            name_or_id: The group's display name (case-insensitive) or its id.

        Returns:
            A [`Group`](#group): the same scoped surface as
            [`env()`](#env), pinned to a saved membership rule.

        Raises:
            RootCauseError: The twin has no such group; the message names the
                ones it does have.
        """
        groups = self.groups
        for group in groups:
            if name_or_id in (group.id, group.name):
                return group
        lowered = name_or_id.lower()
        for group in groups:
            if group.name.lower() == lowered:
                return group
        known = ", ".join(group.name for group in groups) or "none saved yet"
        raise RootCauseError(
            f'No environment group "{name_or_id}" on "{self.name}" (known: {known}). '
            'Save one with twin.env(...).save("name").'
        )

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

        Static trained twins only. Blocks until the run completes.

        Args:
            rows: A DataFrame, or a list of dicts whose keys name twin
                variables.
            targets: The outcomes to reach, as
                `[{"variable": ..., "value": ...}]`.
            max_changes: Most variables any one row is allowed to flip.
            constraints: Per-variable limits on what may change, and how far.
            webhook_url: Called with the run result instead of waiting on it.
            timeout: Seconds to wait for the run.

        Returns:
            A [`ScoreResult`](#scoreresult) covering every row.
        """
        rows = _guard.records(rows, "rows")
        if not targets:
            raise InvalidArgumentError(
                'targets= must name at least one outcome to reach, as [{"variable": ..., "value": ...}]'
            )
        body: dict[str, Any] = {"rows": rows, "targets": targets, "maxChanges": _guard.positive(max_changes, "max_changes")}
        if constraints:
            body["constraints"] = constraints
        if webhook_url:
            body["webhookUrl"] = webhook_url
        envelope = self._transport.request("POST", f"{self._version_path()}/score", json_body=body)
        run_id = expect(envelope, "runId", "scoring run")
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

        Args:
            n: Draws per sampling unit.
            do: Interventions to apply before sampling, as
                `{"variable": rc.set(value)}`. A bare value means `rc.set`.
            where: Scope the draws to a subpopulation: `{"region": "EMEA"}` for
                equality, or `{"income": ("<", 5000)}` with any of
                `== != > < >= <=`, plus `in` and `not_in`.
            environments: Panel twins: which environments to sample. Each is
                sampled independently.
            seed: Seed for reproducible draws. Panel twins derive stable
                per-environment child seeds from it.

        Returns:
            The draws as [`SampleDraws`](#sampledraws).

        Raises:
            RootCauseError: `environments` was passed for a twin that is not a
                panel twin.
        """
        n = _guard.positive(n, "n")
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

        Interventions measure their effect through metrics: pass
        `metrics=[rc.metric(...)]` for full control, or `outcomes=["revenue"]`
        for mean-of-column metrics. For raw effect distributions without
        metrics, use `twin.sample(do=...)`.

        Args:
            do: The interventions, as `{"variable": rc.set(value)}`. A bare
                value means `rc.set`; `rc.range(...)` sweeps instead of pinning.
            where: Scope the intervention to a subpopulation: `{"region":
                "EMEA"}` for equality, or `{"income": ("<", 5000)}` with any of
                `== != > < >= <=`, plus `in` and `not_in`.
            metrics: Metrics to measure the effect through, from `rc.metric()`.
            outcomes: Column names to measure as mean-of-column metrics, when
                `metrics` is not given.
            environments: Panel twins: which environments to simulate.
            timeout: Seconds to wait for the run.

        Returns:
            A [`SimulationResult`](#simulationresult).

        Raises:
            RootCauseError: Neither `metrics` nor `outcomes` was given.
        """
        scenario = self._intervention_scenario(do, where, metrics, outcomes, environments)
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

        Args:
            horizon: How many steps ahead to forecast.
            targets: Variables to forecast. Inferred from the twin when omitted.
            environments: Panel twins: which environments to forecast.
            confidence: Width of the prediction interval, as a probability.
            origin_timestamp: Anchor the forecast start (ms epoch). How a
                backtest aligns a forecast against data the twin never saw.
            aggregate: Panel twins: add a combined series across environments,
                one of `sum`, `avg`, `min`, `max`.
            timeout: Seconds to wait for the run.

        Returns:
            A [`ForecastResult`](#forecastresult), tidy long format.

        Raises:
            RootCauseError: The twin is not temporal, or `aggregate` was passed
                for a twin that is not a panel twin.
        """
        scenario = self._forecast_scenario(horizon, targets, environments, confidence, origin_timestamp, aggregate)
        result = self._run_scenario(scenario, timeout=timeout)
        return ForecastResult(self._transport, self._workspace_id, result.run_id, result.run, scenario)

    def predict(
        self,
        sample: "pd.DataFrame | list[dict[str, Any]]",
        targets: list[str] | None = None,
        confidence: float = 0.95,
        *,
        timeout: float = 3600.0,
    ) -> PredictionResult:
        """Predict target outcomes for input records, with uncertainty intervals.

        One prediction per input record: the model reads the values you supply
        as the drivers and answers for the targets you name. Static twins only:
        a temporal twin projects forward with `forecast()` instead.

        Args:
            sample: The input records, as a DataFrame or a list of dicts keyed
                by twin variable name. Leave the target columns out: those are
                what the model answers with.
            targets: Variables to predict. Inferred from the twin when omitted.
            confidence: Width of the uncertainty interval, as a probability.
            timeout: Seconds to wait for the run.

        Returns:
            A [`PredictionResult`](#predictionresult), one row per input record.

        Raises:
            RootCauseError: The twin is temporal, where `forecast()` is the verb.

        Examples:
            >>> twin.predict([{"tenure": 3, "MonthlyCharges": 85.0}], targets=["Churn"])
        """
        scenario = self._prediction_scenario(sample, targets, confidence)
        result = self._run_scenario(scenario, timeout=timeout)
        return PredictionResult(self._transport, self._workspace_id, result.run_id, result.run, scenario)

    def explain(
        self,
        cause: str | None = None,
        effect: str | None = None,
        mode: str | None = None,
        environments: list[str] | None = None,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        """Explain a causal relationship: what a variable drives, or what drives it.

        The mode follows from what you name, so you rarely pass it: `cause=`
        alone asks what that variable goes on to affect (`impact`), `effect=`
        alone asks what drives it (`discovery`), and both together explain the
        paths from one to the other (`directional`).

        Args:
            cause: The upstream variable, for `impact` and `directional`.
            effect: The downstream variable, for `discovery` and `directional`.
            mode: Override the mode: `directional`, `discovery`, or `impact`.
            environments: Panel twins: which environments to explain.
            timeout: Seconds to wait for the run.

        Returns:
            A [`SimulationResult`](#simulationresult).

        Raises:
            RootCauseError: Neither variable was named, the mode is unknown, the
                mode is missing a variable it needs, or `environments` was
                passed for a twin that is not a panel twin.

        Examples:
            >>> twin.explain(effect="Churn")
            >>> twin.explain(cause="Contract", effect="Churn")
        """
        scenario = self._explanation_scenario(cause, effect, mode, environments)
        return self._run_scenario(scenario, timeout=timeout)

    def optimise(
        self,
        objectives: list[dict[str, Any]],
        decision_vars: list[str],
        horizon: int | None = None,
        environments: list[str] | None = None,
        variable_constraints: list[dict[str, Any]] | None = None,
        metric_constraints: list[dict[str, Any]] | None = None,
        max_changes: int | None = None,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        """Search for the actions that best move your objectives.

        The optimizer may only touch the variables you list in
        `decision_vars`, and it measures every plan through the objectives'
        SQL, so an objective naming a variable nothing in `decision_vars` can
        reach has no plan to find.

        Args:
            objectives: What to move and which way, from `rc.objective()`.
            decision_vars: The variables the optimizer is allowed to change.
            horizon: Temporal twins: how many steps ahead the plan runs over.
                Required for a temporal twin, refused for a static one.
            environments: Panel twins: which environments to optimize over.
            variable_constraints: Bounds on how far each variable may move.
            metric_constraints: Guardrails every plan must respect.
            max_changes: Cap on how many variables a single plan may change.
            timeout: Seconds to wait for the run.

        Returns:
            A [`SimulationResult`](#simulationresult).

        Raises:
            RootCauseError: No objectives or no decision variables, an objective
                that is not a `rc.objective()` payload, a horizon that this twin
                kind does not take (or a temporal twin given none), or
                `environments` on a twin that is not a panel twin.

        Examples:
            >>> churn = rc.objective(
            ...     "Churn share",
            ...     "SELECT AVG(CASE WHEN Churn = 'Yes' THEN 1.0 ELSE 0.0 END) AS value FROM df",
            ...     "minimise",
            ... )
            >>> twin.optimise([churn], decision_vars=["Contract", "MonthlyCharges"])
        """
        scenario = self._optimisation_scenario(
            objectives, decision_vars, horizon, environments,
            variable_constraints, metric_constraints, max_changes,
        )
        return self._run_scenario(scenario, timeout=timeout)

    def root_cause(
        self,
        target: str,
        samples: "pd.DataFrame | list[dict[str, Any]] | dict[str, list[dict[str, Any]]]",
        environments: list[str] | None = None,
        timestep: int | None = None,
        target_fpr: float = 0.005,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        """Diagnose one variable: trace it upstream to what actually broke it.

        Use this when you already know which variable is misbehaving. To find
        out whether anything is, scan every variable with `anomalies()`.

        Args:
            target: The variable behaving unexpectedly.
            samples: The observations to diagnose, as a DataFrame, a list of
                dicts, or, on a panel twin, a `{environment: rows}` mapping. A
                flat list on a panel twin is shared across its environments.
            environments: Panel twins: which environments to diagnose.
            timestep: Temporal twins: the step to diagnose. Defaults to the
                one the scan flags.
            target_fpr: Detection sensitivity, as a false-positive rate between
                0.0001 and 0.1. Lower flags less.
            timeout: Seconds to wait for the run.

        Returns:
            A [`SimulationResult`](#simulationresult).

        Raises:
            RootCauseError: No target, `environments` or per-environment samples
                on a twin that is not a panel twin, or `timestep` on a twin with
                no time axis.

        Examples:
            >>> twin.root_cause("Churn", observed_frame)
        """
        scenario = self._root_cause_scenario(target, samples, environments, timestep, target_fpr)
        return self._run_scenario(scenario, timeout=timeout)

    def anomalies(
        self,
        samples: "pd.DataFrame | list[dict[str, Any]] | dict[str, list[dict[str, Any]]]",
        environments: list[str] | None = None,
        start_step: int | None = None,
        end_step: int | None = None,
        target_fpr: float = 0.005,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        """Scan every variable for causal anomalies, and diagnose what it finds.

        The counterpart to `root_cause()`: this one asks whether anything is
        broken rather than why a named variable is.

        Args:
            samples: The observations to scan, as a DataFrame, a list of dicts,
                or, on a panel twin, a `{environment: rows}` mapping. A flat
                list on a panel twin is shared across its environments.
            environments: Panel twins: which environments to scan.
            start_step: Temporal twins: first step of the window to scan.
            end_step: Temporal twins: last step of the window to scan.
            target_fpr: Detection sensitivity, as a false-positive rate between
                0.0001 and 0.1. Lower flags less.
            timeout: Seconds to wait for the run.

        Returns:
            A [`SimulationResult`](#simulationresult).

        Raises:
            RootCauseError: `environments` or per-environment samples on a twin
                that is not a panel twin, or a step window on a twin with no
                time axis.

        Examples:
            >>> twin.anomalies(observed_frame)
        """
        scenario = self._anomaly_scenario(samples, environments, start_step, end_step, target_fpr)
        return self._run_scenario(scenario, timeout=timeout)

    def _intervention_scenario(
        self,
        do: dict[str, Any],
        where: Any,
        metrics: list[dict[str, Any]] | None,
        outcomes: list[str] | None,
        environments: list[str] | None,
    ) -> dict[str, Any]:
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
            return {
                "type": "panel_intervention",
                "interventions": interventions,
                "metrics": metrics or [],
                "environments": environments,
            }
        if self.is_temporal:
            return {"type": "temporal_intervention", "interventions": interventions, "metrics": metrics or []}
        return {"type": "intervention", "interventions": interventions, "metrics": metrics or []}

    def _forecast_scenario(
        self,
        horizon: int,
        targets: list[str] | None,
        environments: list[str] | None,
        confidence: float,
        origin_timestamp: int | None,
        aggregate: str | None,
    ) -> dict[str, Any]:
        if not self.is_temporal:
            raise RootCauseError(
                f'"{self.name}" is a {self.kind} twin; forecasting needs a temporal or panel-temporal twin'
            )
        if aggregate is not None and not self.is_panel:
            raise RootCauseError(f'aggregate= only applies to panel twins; "{self.name}" is {self.kind}')
        horizon = _guard.positive(horizon, "horizon")
        confidence = _guard.probability(confidence, "confidence")
        if aggregate is not None:
            _guard.choice(aggregate, "aggregate", AGGREGATES)
        scenario: dict[str, Any] = {
            "type": "panel_forecast" if self.is_panel else "forecast",
            "forecastH": horizon,
            "targetVars": targets or self._infer_targets(),
            "confidenceLevel": confidence,
            "originTimestamp": origin_timestamp,
        }
        if self.is_panel:
            scenario["environments"] = environments
            scenario["aggregateMode"] = aggregate
        return scenario

    def _prediction_scenario(
        self,
        sample: Any,
        targets: list[str] | None,
        confidence: float,
    ) -> dict[str, Any]:
        if self.kind not in PREDICT_KINDS:
            raise RootCauseError(
                f'"{self.name}" is a {self.kind} twin; prediction reads one row at a time and needs a '
                "static twin. Use forecast() to project a temporal twin forward."
            )
        return {
            "type": "prediction",
            "sample": _guard.records(sample, "sample"),
            "targetVars": targets or self._infer_targets(),
            "confidenceLevel": _guard.probability(confidence, "confidence"),
        }

    def _explanation_scenario(
        self,
        cause: str | None,
        effect: str | None,
        mode: str | None,
        environments: list[str] | None,
    ) -> dict[str, Any]:
        if mode is None:
            mode = "directional" if cause and effect else "impact" if cause else "discovery" if effect else None
        if mode is None:
            raise RootCauseError(
                "An explanation needs a variable to explain: pass effect= for what drives a variable, "
                "cause= for what a variable goes on to affect, or both to explain the paths between them."
            )
        _guard.choice(mode, "mode", EXPLANATION_MODES)
        if mode in {"directional", "impact"} and not cause:
            raise RootCauseError(f'mode="{mode}" needs cause=: the variable whose downstream effects are explained')
        if mode in {"directional", "discovery"} and not effect:
            raise RootCauseError(f'mode="{mode}" needs effect=: the variable whose upstream causes are explained')
        self._reject_environments(environments)
        scenario: dict[str, Any] = {
            "type": self._scenario_type(EXPLANATION_TYPES, "explanation"),
            "explanationMode": mode,
            "causeVariable": cause,
            "effectVariable": effect,
        }
        if self.is_panel:
            scenario["environments"] = environments
        return scenario

    def _optimisation_scenario(
        self,
        objectives: list[dict[str, Any]],
        decision_vars: list[str],
        horizon: int | None,
        environments: list[str] | None,
        variable_constraints: list[dict[str, Any]] | None,
        metric_constraints: list[dict[str, Any]] | None,
        max_changes: int | None,
    ) -> dict[str, Any]:
        if not objectives:
            raise RootCauseError(
                "Optimization needs at least one objective: "
                "objectives=[rc.objective('Revenue', 'SELECT SUM(revenue) AS value FROM df')]"
            )
        for objective in objectives:
            if not isinstance(objective, dict) or not objective.get("variable") or not objective.get("metricSqlQuery"):
                raise RootCauseError(
                    "Every objective needs a name and the SQL that measures it; build them with "
                    f"rc.objective(...). Got: {objective!r}"
                )
        if not decision_vars:
            raise RootCauseError(
                "Optimization needs at least one decision variable: the levers it is allowed to change."
            )
        self._reject_environments(environments)
        scenario_type = self._scenario_type(OPTIMISATION_TYPES, "optimization")
        scenario: dict[str, Any] = {
            "type": scenario_type,
            "objectives": objectives,
            "decisionVars": list(decision_vars),
        }
        if horizon is not None:
            if not self.is_temporal:
                raise RootCauseError(
                    f'horizon= only applies to temporal twins; "{self.name}" is {self.kind} and optimizes '
                    "a single period"
                )
            scenario["forecastHorizon"] = _guard.positive(horizon, "horizon")
        elif scenario_type == "temporal_optimisation":
            raise RootCauseError("A temporal optimization needs horizon=: how many steps ahead the plan runs over")
        if variable_constraints:
            scenario["variableConstraints"] = variable_constraints
        if metric_constraints:
            scenario["metricConstraints"] = metric_constraints
        if max_changes is not None:
            scenario["interventionCountConfig"] = {"maxInterventions": _guard.positive(max_changes, "max_changes")}
        if self.is_panel:
            scenario["environments"] = environments
        return scenario

    def _root_cause_scenario(
        self,
        target: str,
        samples: Any,
        environments: list[str] | None,
        timestep: int | None,
        target_fpr: float,
    ) -> dict[str, Any]:
        if not target:
            raise RootCauseError("root_cause() needs target=: the variable behaving unexpectedly")
        self._reject_environments(environments)
        scenario: dict[str, Any] = {
            "type": self._scenario_type(ROOT_CAUSE_TYPES, "root cause analysis"),
            "targetVariable": target,
            "targetFpr": _guard.bounded(target_fpr, "target_fpr", 0.0001, 0.1),
            **self._scenario_samples(samples),
        }
        if timestep is not None:
            if not self.is_temporal:
                raise RootCauseError(
                    f'timestep= only applies to temporal twins; "{self.name}" is {self.kind} and its rows '
                    "carry no time axis"
                )
            scenario["anomalyTimestep"] = timestep
        if self.is_panel:
            scenario["environments"] = environments
        return scenario

    def _anomaly_scenario(
        self,
        samples: Any,
        environments: list[str] | None,
        start_step: int | None,
        end_step: int | None,
        target_fpr: float,
    ) -> dict[str, Any]:
        self._reject_environments(environments)
        scenario: dict[str, Any] = {
            "type": self._scenario_type(ANOMALY_TYPES, "anomaly detection"),
            "targetFpr": _guard.bounded(target_fpr, "target_fpr", 0.0001, 0.1),
            **self._scenario_samples(samples),
        }
        if (start_step is not None or end_step is not None) and not self.is_temporal:
            raise RootCauseError(
                f'start_step= and end_step= only apply to temporal twins; "{self.name}" is {self.kind} and '
                "its rows carry no time axis"
            )
        if start_step is not None:
            scenario["startStep"] = start_step
        if end_step is not None:
            scenario["endStep"] = end_step
        if self.is_panel:
            scenario["environments"] = environments
        return scenario

    def _scenario_type(self, types: dict[str, str], family: str) -> str:
        """The name this twin's kind gives one scenario family."""
        scenario_type = types.get(self.kind)
        if scenario_type is None:
            raise RootCauseError(
                f'"{self.name}" reports kind "{self.kind}", which this SDK has no {family} scenario for; '
                f"known kinds are {', '.join(sorted(types))}"
            )
        return scenario_type

    def _reject_environments(self, environments: list[str] | None) -> None:
        if environments is not None and not self.is_panel:
            raise RootCauseError(f'environments= only applies to panel twins; "{self.name}" is {self.kind}')

    def _scenario_samples(self, samples: Any, argument: str = "samples") -> dict[str, Any]:
        """Rows shared across the twin, or one set of rows per environment."""
        if isinstance(samples, dict):
            if not self.is_panel:
                raise RootCauseError(
                    f'{argument}= as a {{environment: rows}} mapping only applies to panel twins; '
                    f'"{self.name}" is {self.kind}, so pass one flat list of rows'
                )
            if not samples:
                raise InvalidArgumentError(f"{argument}= names no environments; there is nothing to diagnose")
            return {
                "panelSamples": {
                    str(environment): _guard.records(rows, f"{argument}[{environment!r}]")
                    for environment, rows in samples.items()
                }
            }
        return {"samples": _guard.records(samples, argument)}

    def ask(self, query: str, *, timeout: float = 3600.0) -> SimulationResult:
        """Natural-language question, turned into a scenario and executed.

        Args:
            query: The question, in plain language.
            timeout: Seconds to wait for the run.

        Returns:
            A [`SimulationResult`](#simulationresult); `result.scenario` is what
            the translator produced.
        """
        envelope = self._transport.request(
            "POST", f"{self._version_path()}/scenario-from-query", json_body={"query": query}
        )
        data = envelope.get("data", envelope)
        scenario = data.get("scenario") if isinstance(data, dict) else None
        if not isinstance(scenario, dict):
            raise RootCauseError(
                "Could not turn that question into a scenario. Name the variables to change, what to "
                f"change them to, and the outcome of interest. The translator answered: {str(data)[:200]}"
            )
        return self._run_scenario(scenario, timeout=timeout)

    def console(self, *, height: int = 560, theme: str = "") -> "Any":
        """The interactive causal-graph console under the cell: the same app Claude renders.

        Explore edges, type intervention values, and re-run scenarios; every
        control round-trips live through the platform's MCP gateway with this
        session's credentials. Needs: pip install "rootcause-sdk[jupyter]".

        Args:
            height: Height of the mounted app, in pixels.
            theme: `light`, `dark`, or empty to follow the notebook.

        Returns:
            The mounted widget, displayed by the notebook cell.
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

    def sankey(
        self,
        node: str | None = None,
        *,
        edge: "tuple[str, str] | None" = None,
        depth: int = 2,
        height: int = 520,
        theme: str = "",
    ) -> "Any":
        """The causal-flow Sankey under the cell: how influence propagates through the graph.

        Pass a variable to see everything flowing into and out of it, or an
        edge to see the paths running through that one link. Needs a resolved
        or trained graph and: pip install "rootcause-sdk[jupyter]".

        Args:
            node: Variable to analyse paths around. Exactly one of `node` and
                `edge` must be given.
            edge: A `(cause, effect)` pair to analyse paths through.
            depth: How many hops to traverse on either side.
            height: Height of the mounted app, in pixels.
            theme: `light`, `dark`, or empty to follow the notebook.

        Returns:
            The mounted widget, displayed by the notebook cell.
        """
        if (node is None) == (edge is None):
            raise InvalidArgumentError("Pass exactly one of node= or edge=(cause, effect)")
        if edge is not None and (not isinstance(edge, tuple) or len(edge) != 2):
            raise InvalidArgumentError("edge= is a (cause, effect) pair of variable names")
        from rootcause.jupyter import app

        arguments: dict[str, Any] = {
            "workspaceId": self._workspace_id,
            "digitalTwinVersionId": self.version_id,
            "depthLimit": depth,
        }
        if node is not None:
            arguments["node"] = node
        else:
            arguments["edge"] = {"source": edge[0], "target": edge[1]}
        return app(
            "analyze_digital_twin_path",
            arguments,
            height=height,
            theme=theme,
            transport=self._transport,
        )

    def review(self, *, height: int = 560, theme: str = "") -> "Any":
        """The graph-review console under the cell: structural findings with accept/reject controls.

        Runs the platform's DAG review (cycles, isolated nodes, weak or
        wrong-direction edges, over-connected hubs) and mounts the interactive
        console over the findings; applying a fix round-trips live through the
        MCP gateway. Needs: pip install "rootcause-sdk[jupyter]".

        Args:
            height: Height of the mounted app, in pixels.
            theme: `light`, `dark`, or empty to follow the notebook.

        Returns:
            The mounted widget, displayed by the notebook cell.
        """
        from rootcause.jupyter import app

        return app(
            "review_digital_twin",
            {
                "workspaceId": self._workspace_id,
                "digitalTwinVersionId": self.version_id,
            },
            height=height,
            theme=theme,
            transport=self._transport,
        )

    def studio(
        self,
        query: str,
        *,
        targets: list[str] | None = None,
        horizon: int | None = None,
        environments: list[str] | None = None,
        aggregate: str | None = None,
        height: int = 640,
        theme: str = "",
    ) -> "Any":
        """Ask a what-if in plain English; the What-If Studio renders the answer under the cell.

        The scenario is inferred from the question and executed server-side;
        the studio draws the result with the dials behind it, so a tweaked
        scenario re-runs live through the MCP gateway without leaving the
        notebook. Needs: pip install "rootcause-sdk[jupyter]".

        Args:
            query: The question, stated completely — which variables change, to
                what, and the outcome of interest.
            targets: Exact outcome variable names, when inference should not
                pick them from the question.
            horizon: Forecast scenarios only: exact number of steps.
            environments: Panel forecasts only: restrict to these environments.
            aggregate: Panel forecasts only: `sum`, `avg`, `min`, or `max`
                across environments.
            height: Height of the mounted app, in pixels.
            theme: `light`, `dark`, or empty to follow the notebook.

        Returns:
            The mounted widget, displayed by the notebook cell.
        """
        from rootcause.jupyter import app

        arguments: dict[str, Any] = {
            "workspaceId": self._workspace_id,
            "digitalTwinVersionId": self.version_id,
            "query": query,
        }
        if targets is not None:
            arguments["targetVars"] = targets
        if horizon is not None:
            arguments["forecastH"] = horizon
        if environments is not None:
            arguments["environments"] = environments
        if aggregate is not None:
            arguments["aggregateMode"] = aggregate
        return app(
            "query_digital_twin",
            arguments,
            height=height,
            theme=theme,
            transport=self._transport,
        )

    def save(self, path: str | Path, *, include_runs: bool = False, timeout: float = 3600.0) -> Path:
        """Export this twin (trained params included) as a portable .rctwin zip.

        Args:
            path: Where to write the `.rctwin` file. A directory writes
                `<twin name>.rctwin` inside it.
            include_runs: Include the simulation run history in the export.
            timeout: Seconds to wait for the export job.

        Returns:
            The path written, ready for `rc.load_twin()`.

        Raises:
            InvalidArgumentError: The destination directory does not exist. The
                check runs before the export job starts.
        """
        target = self._export_target(path)
        envelope = self._transport.request(
            "POST", f"{self._twin_path()}/export", json_body={"includeRuns": include_runs}
        )
        job_id = expect(envelope, "jobId", "export job")
        poll_job(self._transport, self._workspace_id, job_id, label=f"export {self.name}", timeout=timeout)
        blob = self._transport.request_bytes("GET", f"{self._twin_path()}/export/{job_id}/download")
        try:
            target.write_bytes(blob)
        except OSError as error:
            raise InvalidArgumentError(f"Could not write {target}: {error.strerror or error}") from error
        return target

    def _export_target(self, path: str | Path) -> Path:
        """Where save() will write, settled before the export job runs."""
        target = Path(path).expanduser()
        if target.is_dir():
            target = target / f"{self.name}.rctwin"
        if not target.parent.exists():
            raise InvalidArgumentError(f"No directory {target.parent} to write {target.name} into")
        return target

    def _run_scenario(
        self,
        scenario: dict[str, Any],
        *,
        timeout: float,
        environment_group_ids: list[str] | None = None,
    ) -> SimulationResult:
        body: dict[str, Any] = {
            "digitalTwinId": self.id,
            "digitalTwinVersionId": self.version_id,
            "scenario": scenario,
        }
        if environment_group_ids is not None:
            body["environmentGroupIds"] = environment_group_ids
        envelope = self._transport.request(
            "POST",
            f"/api/v1/workspaces/{self._workspace_id}/simulations",
            json_body=body,
        )
        run_id = expect(envelope, "runId", "simulation run")
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


_ENV_REDUCERS = {"value": "value", "avg": "mean", "mean": "mean", "min": "min", "max": "max", "any": "any"}

# The engine's operator vocabulary is the UI's label strings; symbols map onto them.
_ENV_OPERATORS = {
    "==": "equal to", "=": "equal to", "eq": "equal to", "equal to": "equal to",
    "!=": "Not Equal to", "<>": "Not Equal to", "neq": "Not Equal to", "Not Equal to": "Not Equal to",
    "<": "Less than", "lt": "Less than", "Less than": "Less than",
    ">": "Greater than", "gt": "Greater than", "Greater than": "Greater than",
    "<=": "Less than or equal to", "lte": "Less than or equal to",
    "Less than or equal to": "Less than or equal to",
    ">=": "Greater than or equal to", "gte": "Greater than or equal to",
    "Greater than or equal to": "Greater than or equal to",
    "contains": "Contains", "Contains": "Contains",
    "is empty": "Is Empty", "Is Empty": "Is Empty",
    "not empty": "Is not Empty", "Is not Empty": "Is not Empty",
}


def _compile_env_where(where: "list[tuple] | dict[str, Any]") -> dict[str, Any]:
    """Tuples -> the engine's stat-filter group; dicts pass through as written."""
    if isinstance(where, dict):
        return where
    filters: list[dict[str, Any]] = []
    for item in where:
        if not isinstance(item, tuple) or len(item) not in (3, 4):
            raise RootCauseError(
                "where= items are (column, op, value) or (column, reduce, op, value) tuples"
            )
        if len(item) == 3:
            column, op, value = item
            reduce = "value"
        else:
            column, reduce, op, value = item
            if reduce not in _ENV_REDUCERS:
                raise RootCauseError(
                    f'Unknown reduce "{reduce}"; one of {sorted(set(_ENV_REDUCERS))}'
                )
            reduce = _ENV_REDUCERS[reduce]
        operator = _ENV_OPERATORS.get(str(op))
        if operator is None:
            raise RootCauseError(
                f'Unknown operator "{op}"; use ==, !=, <, >, <=, >=, contains, '
                f'"is empty", or "not empty"'
            )
        filters.append({
            "column": column,
            "reduce": reduce,
            "comparisonOperator": operator,
            "value": value,
        })
    return {"booleanOperator": "AND", "filters": filters}


class EnvSubset:
    """A panel twin pinned to a subset of its environments.

    Everything on the handle runs scoped to the subset: `graph` re-aggregates
    the causal adjacency over just these environments, and sample/intervene/
    forecast delegate to the twin with environments= filled in.
    """

    def __init__(
        self,
        twin: Twin,
        environments: list["str | dict[str, str]"],
        stat_filters: dict[str, Any] | None = None,
    ) -> None:
        self.twin = twin
        self._requested = environments
        self._stat_filters = stat_filters
        self._resolved: dict[str, Any] | None = None

    def _resolve_filters(self) -> dict[str, Any]:
        if self._resolved is None:
            envelope = self.twin._transport.request(
                "POST",
                f"{self.twin._version_path()}/environments/resolve",
                json_body={"statFilters": self._stat_filters},
            )
            self._resolved = envelope.get("data", envelope)
        return self._resolved

    def _server_resolved(self) -> bool:
        return self._stat_filters is not None

    @property
    def environments(self) -> "pd.DataFrame":
        """The environments this handle covers, resolved to a DataFrame.

        For where= handles the stat filters run server-side; the frame carries
        envKey plus one column per environment column, with totalEnvCount and
        sampleSize in `frame.attrs`.
        """
        import pandas as pd

        if self._server_resolved():
            resolved = self._resolve_filters()
            rows = [
                {"envKey": key, **combo}
                for key, combo in zip(resolved.get("envKeys") or [], resolved.get("environments") or [])
            ]
            frame = pd.DataFrame(rows)
            frame.attrs["totalEnvCount"] = resolved.get("totalEnvCount")
            frame.attrs["sampleSize"] = resolved.get("sampleSize")
            return frame
        combos = self.combos()
        payload = self._listing()
        columns = [str(c) for c in (payload.get("environmentColumns") or [])]
        rows = []
        for entry in payload.get("environments") or []:
            values = [str(v) for v in (entry.get("values") or [])]
            combo = dict(zip(columns, values))
            if combo in combos:
                rows.append({"envKey": entry.get("envKey"), "sampleSize": entry.get("sampleSize"), **combo})
        return pd.DataFrame(rows)

    def _listing(self) -> dict[str, Any]:
        envelope = self.twin._transport.request("GET", f"{self.twin._version_path()}/environments")
        payload = envelope.get("data", envelope)
        return payload if isinstance(payload, dict) else {}

    def combos(self) -> list[dict[str, str]]:
        """The subset as exact {column: value} combos, resolved against the twin's environments.

        The listing carries each environment's values as a list ordered by
        environmentColumns; zipping the two recovers the combo.
        """
        if self._server_resolved():
            return [dict(c) for c in (self._resolve_filters().get("environments") or [])]
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
        if self._server_resolved():
            return [str(k) for k in (self._resolve_filters().get("envKeys") or [])]
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

    def _definition(self) -> dict[str, Any]:
        if self._stat_filters is not None:
            return {"mode": "statFilters", "statFilters": self._stat_filters}
        return {"mode": "environments", "environments": self.combos()}

    def save(self, name: str) -> "Group":
        """Save this subset on the twin as a named environment group.

        The group lives on the twin rather than on a version, so it survives
        retraining, appears in the platform's environment picker straight away,
        and comes back next session as `twin.group(name)`. What gets stored is
        the rule, not the answer: a `where=` subset saves its filters and
        re-selects environments as the data moves, while a named subset saves
        the exact combos it resolved to.

        ```python
        eu = twin.env("london", "berlin").save("EU stores")
        twin.group("EU stores").intervene({"price": rc.pct(-10)}, outcomes=["revenue"])
        ```

        Args:
            name: Display name, unique per twin.

        Returns:
            The saved [`Group`](#group).

        Raises:
            RootCauseError: The twin already has a group with this name, or is
                at its group cap.
        """
        try:
            envelope = self.twin._transport.request(
                "POST",
                f"{self.twin._twin_path()}/environment-groups",
                json_body={"name": name, "definition": self._definition()},
            )
        except RootCauseApiError as error:
            if error.status == 409:
                raise RootCauseError(
                    f'Could not save "{name}" on "{self.twin.name}": {error.detail} Group names are '
                    f'unique per twin — pick another name, or change the existing group with '
                    f'twin.group("{name}").update(...).'
                ) from error
            raise
        return Group(self.twin, envelope.get("data", envelope))

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

    def explain(
        self,
        cause: str | None = None,
        effect: str | None = None,
        mode: str | None = None,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        return self.twin.explain(
            cause=cause, effect=effect, mode=mode, environments=self._names(), timeout=timeout
        )

    def optimise(
        self,
        objectives: list[dict[str, Any]],
        decision_vars: list[str],
        horizon: int | None = None,
        variable_constraints: list[dict[str, Any]] | None = None,
        metric_constraints: list[dict[str, Any]] | None = None,
        max_changes: int | None = None,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        return self.twin.optimise(
            objectives,
            decision_vars,
            horizon=horizon,
            environments=self._names(),
            variable_constraints=variable_constraints,
            metric_constraints=metric_constraints,
            max_changes=max_changes,
            timeout=timeout,
        )

    def root_cause(
        self,
        target: str,
        samples: "pd.DataFrame | list[dict[str, Any]] | dict[str, list[dict[str, Any]]]",
        timestep: int | None = None,
        target_fpr: float = 0.005,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        return self.twin.root_cause(
            target, samples, environments=self._names(), timestep=timestep,
            target_fpr=target_fpr, timeout=timeout,
        )

    def anomalies(
        self,
        samples: "pd.DataFrame | list[dict[str, Any]] | dict[str, list[dict[str, Any]]]",
        start_step: int | None = None,
        end_step: int | None = None,
        target_fpr: float = 0.005,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        return self.twin.anomalies(
            samples, environments=self._names(), start_step=start_step, end_step=end_step,
            target_fpr=target_fpr, timeout=timeout,
        )

    def __repr__(self) -> str:
        if self._stat_filters is not None:
            if self._resolved is not None:
                matched = len(self._resolved.get("envKeys") or [])
                return f"EnvSubset({self.twin.name!r}, where-matched={matched})"
            return f"EnvSubset({self.twin.name!r}, where=<unresolved>)"
        labels = ", ".join(
            "/".join(item.values()) if isinstance(item, dict) else str(item) for item in self._requested
        )
        return f"EnvSubset({self.twin.name!r}, environments=[{labels}])"

    def link(self) -> "Any":
        """The parent twin's page on the platform, as a clickable URL."""
        return self.twin.link()

    def _repr_html_(self) -> str:
        return f"<div><p><b>{self!r}</b></p>{self.environments.head(20)._repr_html_()}</div>"

    def _ipython_display_(self) -> None:
        from rootcause import jupyter
        from rootcause._display import show

        show(self, lambda: jupyter.app(
            "list_twin_environments",
            {
                "workspaceId": self.twin._workspace_id,
                "digitalTwinVersionId": self.twin.version_id,
            },
            transport=self.twin._transport,
        ))


class Group(EnvSubset):
    """A saved environment group: the same scoped surface as a subset, kept on the twin.

    Everything an [`EnvSubset`](#envsubset) does, a group does against its
    current membership — the rule is stored, not the answer, so it is resolved
    against this handle's version on first use and re-resolved after an edit.
    Simulations name the group rather than expanding it, so the run records
    which group it covered and what that meant at submit time.

    Attributes:
        doc (dict): The stored group document.
    """

    def __init__(self, twin: Twin, doc: dict[str, Any]) -> None:
        super().__init__(twin, [])
        self.doc = doc

    @property
    def id(self) -> str:
        return str(self.doc.get("id") or self.doc.get("_id"))

    @property
    def name(self) -> str:
        return str(self.doc.get("name", self.id))

    @property
    def definition(self) -> dict[str, Any]:
        """The stored membership rule: `environments`, `columnValues`, or `statFilters` mode."""
        definition = self.doc.get("definition")
        return definition if isinstance(definition, dict) else {}

    def _path(self) -> str:
        return f"{self.twin._twin_path()}/environment-groups/{self.id}"

    def _server_resolved(self) -> bool:
        return True

    def _resolve_filters(self) -> dict[str, Any]:
        if self._resolved is None:
            envelope = self.twin._transport.request(
                "POST",
                f"{self.twin._version_path()}/environment-groups/resolve",
                json_body={"groupId": self.id},
            )
            resolved = envelope.get("data", envelope)
            resolved = resolved if isinstance(resolved, dict) else {}
            unresolvable = resolved.get("unresolvable")
            if isinstance(unresolvable, dict):
                columns = ", ".join(str(c) for c in (unresolvable.get("columns") or []))
                reason = f'{unresolvable.get("reason")}; columns: {columns}' if columns else str(unresolvable.get("reason"))
                raise RootCauseError(
                    f'Environment group "{self.name}" does not fit version '
                    f'{self.twin.version_id} of "{self.twin.name}": '
                    f'{unresolvable.get("message") or unresolvable.get("reason")} [{reason}]'
                )
            self._resolved = resolved
        return self._resolved

    def _definition(self) -> dict[str, Any]:
        return self.definition

    def rename(self, name: str) -> "Group":
        """Rename the group in place.

        Args:
            name: The new display name, unique per twin.

        Returns:
            This group.

        Raises:
            RootCauseError: The twin already has a group with this name.
        """
        return self._patch({"name": name})

    def update(
        self,
        *environments: "str | dict[str, str]",
        where: "list[tuple] | dict[str, Any] | None" = None,
        definition: dict[str, Any] | None = None,
    ) -> "Group":
        """Replace the group's membership rule, in the same vocabulary as `twin.env()`.

        ```python
        group.update("london", "berlin", "paris")            # exact environments
        group.update(where=[("revenue", "avg", ">", 400)])   # a filter, re-selected as data moves
        ```

        Runs already submitted keep the membership frozen on their snapshots;
        every later read of the group sees the new rule.

        Args:
            *environments: Environment names, envKeys, or `{column: value}`
                combos, as [`env()`](#env) takes them.
            where: Stat filters instead of names, as [`env()`](#env) takes
                them.
            definition: A raw definition document, when you have one already.

        Returns:
            This group, on the new rule.

        Raises:
            RootCauseError: None (or more than one) of the three selection
                styles was passed.
        """
        chosen = [bool(environments), where is not None, definition is not None]
        if sum(chosen) != 1:
            raise RootCauseError(
                "Pass exactly one of environments, where=, or definition= to update a group"
            )
        if definition is None:
            definition = self.twin.env(*environments, where=where)._definition()
        return self._patch({"definition": definition})

    def delete(self) -> None:
        """Delete the group from the twin.

        Nothing downstream goes with it: runs scoped to the group keep their
        snapshots. Deleting a group that is already gone is a no-op.
        """
        try:
            self.twin._transport.request("DELETE", self._path())
        except RootCauseApiError as error:
            if error.status != 404:
                raise

    def _patch(self, body: dict[str, Any]) -> "Group":
        try:
            envelope = self.twin._transport.request("PATCH", self._path(), json_body=body)
        except RootCauseApiError as error:
            if error.status == 409:
                raise RootCauseError(
                    f'Could not update "{self.name}": {error.detail} Group names are unique per twin.'
                ) from error
            raise
        doc = envelope.get("data", envelope)
        if isinstance(doc, dict) and doc:
            self.doc = doc
        self._resolved = None
        return self

    def intervene(
        self,
        do: dict[str, Any],
        where: Any = None,
        metrics: list[dict[str, Any]] | None = None,
        outcomes: list[str] | None = None,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        scenario = self.twin._intervention_scenario(do, where, metrics, outcomes, None)
        return self.twin._run_scenario(scenario, timeout=timeout, environment_group_ids=[self.id])

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
        scenario = self.twin._forecast_scenario(horizon, targets, None, confidence, origin_timestamp, aggregate)
        result = self.twin._run_scenario(scenario, timeout=timeout, environment_group_ids=[self.id])
        return ForecastResult(
            self.twin._transport, self.twin._workspace_id, result.run_id, result.run, scenario
        )

    def explain(
        self,
        cause: str | None = None,
        effect: str | None = None,
        mode: str | None = None,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        scenario = self.twin._explanation_scenario(cause, effect, mode, None)
        return self.twin._run_scenario(scenario, timeout=timeout, environment_group_ids=[self.id])

    def optimise(
        self,
        objectives: list[dict[str, Any]],
        decision_vars: list[str],
        horizon: int | None = None,
        variable_constraints: list[dict[str, Any]] | None = None,
        metric_constraints: list[dict[str, Any]] | None = None,
        max_changes: int | None = None,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        scenario = self.twin._optimisation_scenario(
            objectives, decision_vars, horizon, None,
            variable_constraints, metric_constraints, max_changes,
        )
        return self.twin._run_scenario(scenario, timeout=timeout, environment_group_ids=[self.id])

    def root_cause(
        self,
        target: str,
        samples: "pd.DataFrame | list[dict[str, Any]] | dict[str, list[dict[str, Any]]]",
        timestep: int | None = None,
        target_fpr: float = 0.005,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        scenario = self.twin._root_cause_scenario(target, samples, None, timestep, target_fpr)
        return self.twin._run_scenario(scenario, timeout=timeout, environment_group_ids=[self.id])

    def anomalies(
        self,
        samples: "pd.DataFrame | list[dict[str, Any]] | dict[str, list[dict[str, Any]]]",
        start_step: int | None = None,
        end_step: int | None = None,
        target_fpr: float = 0.005,
        *,
        timeout: float = 3600.0,
    ) -> SimulationResult:
        scenario = self.twin._anomaly_scenario(samples, None, start_step, end_step, target_fpr)
        return self.twin._run_scenario(scenario, timeout=timeout, environment_group_ids=[self.id])

    def link(self) -> "Any":
        """The parent twin's page on the platform, as a clickable URL."""
        return self.twin.link()

    def __repr__(self) -> str:
        if self._resolved is not None:
            return f"Group({self.name!r}, environments={len(self._resolved.get('envKeys') or [])})"
        return f"Group({self.name!r}, id={self.id})"
