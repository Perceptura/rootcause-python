import pytest

import rootcause as rc
from rootcause.interventions import compile_do, compile_where


def test_spec_builders_emit_backend_shapes():
    assert rc.set(120) == {"type": "set_value", "value": 120}
    assert rc.pct(+15) == {"type": "relative_change", "mode": "percentage", "value": 15}
    assert rc.add(-5) == {"type": "relative_change", "mode": "absolute", "value": -5}
    assert rc.prob("yes", 0.8) == {"type": "set_probability", "category": "yes", "probability": 0.8}
    assert rc.prob({"yes": 0.8}) == {"type": "set_probability", "category": "yes", "probability": 0.8}
    assert rc.adjust_prob("yes", +10) == {"type": "adjust_probability", "category": "yes", "delta": 10.0}
    assert rc.members(include=["Alice"], size=4) == {
        "type": "set_members", "include": ["Alice"], "exclude": None, "size": 4, "replace": False,
    }


def test_prob_dict_requires_single_pair():
    with pytest.raises(ValueError):
        rc.prob({"yes": 0.8, "no": 0.2})


def test_where_equality_shorthand_and_tuples():
    assert compile_where({"region": "EMEA"}) == [{"variable": "region", "operator": "eq", "value": "EMEA"}]
    assert compile_where({"re75": ("<", 5000)}) == [{"variable": "re75", "operator": "<", "value": 5000}]


def test_where_rejects_unknown_operator():
    with pytest.raises(ValueError):
        compile_where({"x": ("~=", 1)})


def test_compile_do_bare_value_means_set():
    interventions = compile_do({"price": 120})
    assert interventions == [{"variable": "price", "valueSpec": {"type": "set_value", "value": 120}}]


def test_compile_do_attaches_conditions_to_every_intervention():
    interventions = compile_do({"a": rc.pct(10), "b": 1}, where={"region": "US"})
    assert all(i["conditions"] == [{"variable": "region", "operator": "eq", "value": "US"}] for i in interventions)


def test_compile_do_rejects_empty():
    with pytest.raises(ValueError):
        compile_do({})


def test_at_schedules_temporal_fields_on_the_intervention():
    scheduled = rc.at(rc.pct(-10), persistent=True, duration_steps=6)
    interventions = compile_do({"price": scheduled})
    assert interventions == [{
        "variable": "price",
        "valueSpec": {"type": "relative_change", "mode": "percentage", "value": -10},
        "persistent": True,
        "durationSteps": 6,
    }]


def test_at_accepts_bare_values():
    assert rc.at(42, timestamp=1700000000000)["valueSpec"] == {"type": "set_value", "value": 42}
