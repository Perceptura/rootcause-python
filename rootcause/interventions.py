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
        value_spec = spec if isinstance(spec, dict) and "type" in spec else {"type": "set_value", "value": spec}
        intervention: dict[str, Any] = {"variable": variable, "valueSpec": value_spec}
        if conditions:
            intervention["conditions"] = conditions
        interventions.append(intervention)
    return interventions
