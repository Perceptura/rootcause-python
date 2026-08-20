"""Builders for the `do` and `where` payloads the twin's verbs take.

Every builder returns a plain dict, so a hand-written payload works just as well.
"""

from typing import Any

from rootcause.errors import InvalidArgumentError

_OPERATOR_SYMBOLS = {"==", "!=", "<>", ">", "<", ">=", "<=", "in", "not_in", "eq", "ne", "gt", "lt", "ge", "le"}


def _number(value: Any, argument: str) -> float:
    """Anything the engine will treat as a number, or a sentence about what was passed."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise InvalidArgumentError(f"{argument} takes a number, not {type(value).__name__}")
    try:
        return float(value)
    except ValueError:
        raise InvalidArgumentError(f"{argument} takes a number, not {value!r}") from None


def set(value: float | int | str | bool) -> dict[str, Any]:  # noqa: A001
    """Set the variable to an exact value.

    A bare value anywhere `do=` is accepted means the same thing.

    Args:
        value: The value to pin the variable to.
    """
    return {"type": "set_value", "value": value}


def pct(value: float) -> dict[str, Any]:
    """Relative percentage change: rc.pct(+15) means +15%.

    Args:
        value: The change, in percent.
    """
    return {"type": "relative_change", "mode": "percentage", "value": _number(value, "rc.pct")}


def add(value: float) -> dict[str, Any]:
    """Relative absolute change: rc.add(-5) means minus five units.

    Args:
        value: The change, in the variable's own units.
    """
    return {"type": "relative_change", "mode": "absolute", "value": _number(value, "rc.add")}


def prob(category: str | int | bool | dict[Any, float], probability: float | None = None) -> dict[str, Any]:
    """Set a category's probability: rc.prob("yes", 0.8) or rc.prob({"yes": 0.8}).

    Args:
        category: The category, or a single-pair `{category: probability}` dict.
        probability: The probability, when `category` is not a dict.

    Raises:
        InvalidArgumentError: The dict form carried more than one pair, no
            probability was given, or it is not a probability.
    """
    if isinstance(category, dict):
        if len(category) != 1:
            raise InvalidArgumentError("rc.prob({...}) takes exactly one category: probability pair")
        ((category, probability),) = category.items()
    if probability is None:
        raise InvalidArgumentError('rc.prob needs a probability: rc.prob("yes", 0.8)')
    value = _number(probability, "probability")
    if not 0.0 <= value <= 1.0:
        raise InvalidArgumentError(f"probability must be between 0 and 1, not {value}")
    return {"type": "set_probability", "category": category, "probability": value}


def adjust_prob(category: str | int | bool, delta: float) -> dict[str, Any]:
    """Shift a category's probability by percentage points: rc.adjust_prob("yes", +10).

    Args:
        category: The category to shift.
        delta: The shift, in percentage points.
    """
    return {"type": "adjust_probability", "category": category, "delta": _number(delta, "delta")}


def members(
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    size: int | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Set-valued column intervention: who is in the set, who is out, how big it is.

    Args:
        include: Members that must be in the set.
        exclude: Members that must not be.
        size: How large the set should be.
        replace: Replace the observed membership instead of amending it.
    """
    return {"type": "set_members", "include": include, "exclude": exclude, "size": size, "replace": replace}


def at(
    spec: Any,
    timestamp: int | None = None,
    persistent: bool | None = None,
    duration_steps: int | None = None,
) -> dict[str, Any]:
    """Schedule an intervention in time, for temporal and panel twins.

    Wraps a value spec (or bare value) with when it applies and for how long:
    `rc.at(rc.pct(-10), persistent=True)` applies from the first forecast step
    onwards.

    Args:
        spec: The intervention to schedule, or a bare value.
        timestamp: When it starts (ms epoch). Defaults to the first forecast
            step.
        persistent: Keep applying it for every later step.
        duration_steps: Apply it for this many steps only.
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

    A scenario carries at most one range intervention; read the curves back with
    `result.sweep()`.

    Args:
        from_: Low end of the sweep. Defaults to the variable's observed p05.
        to: High end of the sweep. Defaults to the observed p95.
        steps: How many points to evaluate across the range.
    """
    spec: dict[str, Any] = {"type": "range"}
    if from_ is not None:
        spec["from"] = _number(from_, "from_")
    if to is not None:
        spec["to"] = _number(to, "to")
    if "from" in spec and "to" in spec and spec["from"] >= spec["to"]:
        raise InvalidArgumentError(f'rc.range needs from_ < to, not {spec["from"]} → {spec["to"]}')
    if steps is not None:
        if int(steps) < 2:
            raise InvalidArgumentError(f"rc.range needs at least 2 steps to be a curve, not {steps}")
        spec["steps"] = int(steps)
    return spec


def metric(name: str, sql: str, unit: str = "count", higher_is_better: bool = True) -> dict[str, Any]:
    """A simulation metric: SQL over the sampled frame, registered as df/data/dataset.

    Args:
        name: Name for the metric, as it appears on the result.
        sql: SQL over the sampled frame, which is registered as `df`, `data`,
            and `dataset`.
        unit: Unit label for the metric's value.
        higher_is_better: Which direction counts as an improvement.

    Examples:
        >>> rc.metric("avg_revenue", "SELECT AVG(revenue) AS value FROM df", unit="USD")
    """
    if not str(name).strip():
        raise InvalidArgumentError("A metric needs a name")
    if "select" not in str(sql).lower():
        raise InvalidArgumentError(
            f'metric sql must be a SELECT over the sampled frame, for example '
            f'\'SELECT AVG("{name}") AS value FROM df\'; got: {sql!r}'
        )
    return {"name": name, "sqlQuery": sql, "unit": unit, "higherIsBetter": higher_is_better}


def mean_metrics(outcomes: list[str]) -> list[dict[str, Any]]:
    """Mean-of-column metrics for each outcome variable, the common case.

    Args:
        outcomes: Column names to average.

    Returns:
        One mean-of-column metric per outcome, ready for `metrics=`.
    """
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
        raise InvalidArgumentError(
            f"where= must be a dict, a list of condition dicts, or None, not {type(where).__name__}"
        )

    conditions: list[dict[str, Any]] = []
    for variable, clause in where.items():
        if isinstance(clause, tuple):
            if len(clause) != 2 or str(clause[0]) not in _OPERATOR_SYMBOLS:
                raise InvalidArgumentError(
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
        raise InvalidArgumentError(
            "do= must be a non-empty dict of {variable: value or rc.set/pct/add/prob/members spec}"
        )
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
