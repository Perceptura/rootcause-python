"""Builders for the `do` and `where` payloads the twin's verbs take.

Every builder returns a plain dict, so a hand-written payload works just as well.
"""

from typing import Any

_OPERATOR_SYMBOLS = {"==", "!=", "<>", ">", "<", ">=", "<=", "in", "not_in", "eq", "ne", "gt", "lt", "ge", "le"}


def set(value: float | int | str | bool) -> dict[str, Any]:  # noqa: A001
    """Set the variable to an exact value."""
    return {"type": "set_value", "value": value}


def pct(value: float) -> dict[str, Any]:
    """Relative percentage change: rc.pct(+15) means +15%."""
    return {"type": "relative_change", "mode": "percentage", "value": value}


def add(value: float) -> dict[str, Any]:
    """Relative absolute change: rc.add(-5) means minus five units."""
    return {"type": "relative_change", "mode": "absolute", "value": value}


def prob(category: str | int | bool | dict[Any, float], probability: float | None = None) -> dict[str, Any]:
    """Set a category's probability: rc.prob("yes", 0.8) or rc.prob({"yes": 0.8})."""
    if isinstance(category, dict):
        if len(category) != 1:
            raise ValueError("rc.prob({...}) takes exactly one category: probability pair")
        ((category, probability),) = category.items()
    if probability is None:
        raise ValueError("rc.prob needs a probability")
    return {"type": "set_probability", "category": category, "probability": float(probability)}


def adjust_prob(category: str | int | bool, delta: float) -> dict[str, Any]:
    """Shift a category's probability by percentage points: rc.adjust_prob("yes", +10)."""
    return {"type": "adjust_probability", "category": category, "delta": float(delta)}


def members(
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    size: int | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Set-valued column intervention: who is in the set, who is out, how big it is."""
    return {"type": "set_members", "include": include, "exclude": exclude, "size": size, "replace": replace}


def at(
    spec: Any,
    timestamp: int | None = None,
    persistent: bool | None = None,
    duration_steps: int | None = None,
) -> dict[str, Any]:
    """Schedule an intervention in time, for temporal and panel twins.

    Wraps a value spec (or bare value) with when it applies and for how long:
    rc.at(rc.pct(-10), persistent=True) applies from the first forecast step
    onwards; duration_steps limits it; timestamp (ms epoch) anchors the start.
    """
    value_spec = spec if isinstance(spec, dict) and "type" in spec else {"type": "set_value", "value": spec}
    scheduled: dict[str, Any] = {"valueSpec": value_spec}
    if timestamp is not None:
        scheduled["timestamp"] = int(timestamp)
    if persistent is not None:
        scheduled["persistent"] = bool(persistent)
    if duration_steps is not None:
        scheduled["durationSteps"] = int(duration_steps)
    return scheduled


def range(from_: float | None = None, to: float | None = None, *, steps: int | None = None) -> dict[str, Any]:  # noqa: A001
    """Sweep a numeric variable across a grid instead of pinning it: rc.range(15, 30).

    Omit from_/to to sweep the variable's observed p05..p95. A scenario carries
    at most one range intervention; read the curves back with result.sweep().
    """
    spec: dict[str, Any] = {"type": "range"}
    if from_ is not None:
        spec["from"] = float(from_)
    if to is not None:
        spec["to"] = float(to)
    if steps is not None:
        spec["steps"] = int(steps)
    return spec


def metric(name: str, sql: str, unit: str = "count", higher_is_better: bool = True) -> dict[str, Any]:
    """A simulation metric: SQL over the sampled frame, registered as df/data/dataset.

    Example: rc.metric("avg_revenue", "SELECT AVG(revenue) AS value FROM df", unit="USD")
    """
    return {"name": name, "sqlQuery": sql, "unit": unit, "higherIsBetter": higher_is_better}


def mean_metrics(outcomes: list[str]) -> list[dict[str, Any]]:
    """Mean-of-column metrics for each outcome variable, the common case."""
    return [
        metric(f"avg_{column}", f'SELECT AVG("{column}") AS value FROM df')
        for column in outcomes
    ]


def compile_where(where: Any) -> list[dict[str, Any]]:
    """Compile the friendly where= forms into backend Condition dicts.

    Accepts {"region": "EMEA"} equality shorthand, {"re75": ("<", 5000)} tuples,
    or an explicit list of Condition dicts. Operator spellings pass through as
    typed; the backend aliases symbols like "<" and ">=" itself.
    """
    if where is None:
        return []
    if isinstance(where, list):
        return list(where)
    if not isinstance(where, dict):
        raise TypeError("where= must be a dict, a list of condition dicts, or None")

    conditions: list[dict[str, Any]] = []
    for variable, clause in where.items():
        if isinstance(clause, tuple):
            if len(clause) != 2 or str(clause[0]) not in _OPERATOR_SYMBOLS:
                raise ValueError(
                    f'where clause for "{variable}" must be (operator, value) with operator one of {sorted(_OPERATOR_SYMBOLS)}'
                )
            operator, value = clause
            conditions.append({"variable": variable, "operator": str(operator), "value": value})
        else:
            conditions.append({"variable": variable, "operator": "eq", "value": clause})
    return conditions


def compile_do(do: dict[str, Any], where: Any = None) -> list[dict[str, Any]]:
    """Compile do={variable: spec-or-bare-value} into backend Intervention dicts.

    A bare value is shorthand for rc.set(value). Conditions from where= attach
    to every intervention, scoping the whole do() to that subpopulation.
    """
    if not isinstance(do, dict) or not do:
        raise ValueError("do= must be a non-empty dict of {variable: value or rc.set/pct/add/prob/members spec}")
    conditions = compile_where(where)
    interventions: list[dict[str, Any]] = []
    for variable, spec in do.items():
        if isinstance(spec, dict) and "valueSpec" in spec:
            intervention: dict[str, Any] = {"variable": variable, **spec}
        else:
            value_spec = spec if isinstance(spec, dict) and "type" in spec else {"type": "set_value", "value": spec}
            intervention = {"variable": variable, "valueSpec": value_spec}
        if conditions:
            intervention["conditions"] = conditions
        interventions.append(intervention)
    return interventions
