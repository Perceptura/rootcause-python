import httpx
import pytest

from rootcause.errors import RootCauseError
from rootcause.results import SimulationResult
from rootcause.twin import Group, Twin

WS = "ws1"
TWIN_DOC = {"id": "tw1", "name": "Stores", "type": "multi-environment-temporal"}
VERSION = {"id": "v1", "version": "1.0.0", "lifecycleState": "trained"}

TWIN_PATH = f"/api/v1/workspaces/{WS}/digital-twins/tw1"
VERSION_PATH = f"{TWIN_PATH}/versions/v1"
GROUPS_PATH = f"{TWIN_PATH}/environment-groups"
RESOLVE_PATH = f"{VERSION_PATH}/environment-groups/resolve"

ENV_LISTING = {"data": {
    "environmentColumns": ["store"],
    "environments": [
        {"envKey": "london", "values": ["london"], "sampleSize": 30},
        {"envKey": "berlin", "values": ["berlin"], "sampleSize": 30},
        {"envKey": "paris", "values": ["paris"], "sampleSize": 30},
    ],
}}

EU_GROUP = {
    "id": "grp-eu",
    "name": "EU stores",
    "definition": {"mode": "environments", "environments": [{"store": "london"}, {"store": "berlin"}]},
    "createdAt": "2026-08-01T00:00:00Z",
}
BIG_GROUP = {
    "id": "grp-big",
    "name": "High revenue",
    "definition": {"mode": "statFilters", "statFilters": {
        "booleanOperator": "AND",
        "filters": [{"column": "revenue", "reduce": "mean", "comparisonOperator": "Greater than", "value": 400}],
    }},
    "createdAt": "2026-08-02T00:00:00Z",
}

RESOLVED_EU = {"data": {
    "groupId": "grp-eu",
    "name": "EU stores",
    "environmentColumns": ["store"],
    "environments": [{"store": "london"}, {"store": "berlin"}],
    "envKeys": ["london", "berlin"],
    "sampleSize": 60,
    "totalEnvCount": 3,
    "unresolvedEnvCount": 0,
    "unresolvable": None,
}}


def _twin(transport) -> Twin:
    twin = Twin(transport, WS, dict(TWIN_DOC))
    twin._version_doc = dict(VERSION)
    return twin


def _paths(api, needle: str) -> list[str]:
    return [str(request.url.path) for request in api.requests if needle in str(request.url.path)]


def test_named_subset_saves_as_an_environments_definition(api, transport):
    api.on("GET", f"{VERSION_PATH}/environments", ENV_LISTING)
    api.on("POST", GROUPS_PATH, {"data": EU_GROUP}, status=201)

    group = _twin(transport).env("london", "berlin").save("EU stores")

    assert isinstance(group, Group)
    assert (group.id, group.name) == ("grp-eu", "EU stores")
    assert api.body_of("POST", "/environment-groups") == {
        "name": "EU stores",
        "definition": {"mode": "environments", "environments": [{"store": "london"}, {"store": "berlin"}]},
    }


def test_where_subset_saves_its_compiled_stat_filters(api, transport):
    api.on("POST", GROUPS_PATH, {"data": BIG_GROUP}, status=201)

    group = _twin(transport).env(where=[("revenue", "avg", ">", 400)]).save("High revenue")

    assert group.definition["mode"] == "statFilters"
    assert api.body_of("POST", "/environment-groups") == {
        "name": "High revenue",
        "definition": {"mode": "statFilters", "statFilters": {
            "booleanOperator": "AND",
            "filters": [{"column": "revenue", "reduce": "mean", "comparisonOperator": "Greater than", "value": 400}],
        }},
    }
    assert not _paths(api, "/environments/resolve")


def test_a_subset_matching_nothing_still_saves(api, transport):
    api.on("POST", f"{VERSION_PATH}/environments/resolve", {"data": {
        "environmentColumns": ["store"], "environments": [], "envKeys": [],
        "sampleSize": 0, "totalEnvCount": 3, "unresolvedEnvCount": 0, "unresolvable": None,
    }})
    empty_doc = {"id": "grp-none", "name": "Loss makers", "definition": {
        "mode": "statFilters", "statFilters": {"booleanOperator": "AND", "filters": [
            {"column": "revenue", "reduce": "mean", "comparisonOperator": "Less than", "value": 0},
        ]},
    }}
    api.on("POST", GROUPS_PATH, {"data": empty_doc}, status=201)

    subset = _twin(transport).env(where=[("revenue", "avg", "<", 0)])
    group = subset.save("Loss makers")

    assert group.id == "grp-none"
    assert subset.environments.empty


def test_duplicate_name_is_a_clear_error(api, transport):
    api.on("GET", f"{VERSION_PATH}/environments", ENV_LISTING)
    api.on("POST", GROUPS_PATH, {"title": "Conflict", "detail": 'A group named "EU stores" already exists'}, status=409)

    with pytest.raises(RootCauseError) as exc:
        _twin(transport).env("london").save("EU stores")

    message = str(exc.value)
    assert "EU stores" in message
    assert "unique per twin" in message
    assert "twin.group" in message


def test_groups_lists_saved_groups(api, transport):
    api.on("GET", GROUPS_PATH, {"data": [EU_GROUP, BIG_GROUP]})

    groups = _twin(transport).groups

    assert [group.name for group in groups] == ["EU stores", "High revenue"]
    assert [group.id for group in groups] == ["grp-eu", "grp-big"]
    assert groups[1].definition["mode"] == "statFilters"


def test_groups_is_empty_when_the_twin_has_none(api, transport):
    api.on("GET", GROUPS_PATH, {"data": []})

    assert _twin(transport).groups == []


def test_group_resolves_by_name_and_by_id(api, transport):
    api.on("GET", GROUPS_PATH, {"data": [EU_GROUP, BIG_GROUP]})
    twin = _twin(transport)

    assert twin.group("EU stores").id == "grp-eu"
    assert twin.group("eu stores").id == "grp-eu"
    assert twin.group("grp-big").name == "High revenue"


def test_unknown_group_names_the_known_ones(api, transport):
    api.on("GET", GROUPS_PATH, {"data": [EU_GROUP, BIG_GROUP]})

    with pytest.raises(RootCauseError) as exc:
        _twin(transport).group("APAC")

    message = str(exc.value)
    assert "APAC" in message
    assert "EU stores" in message
    assert "High revenue" in message


def test_unknown_group_on_a_twin_with_none_points_at_save(api, transport):
    api.on("GET", GROUPS_PATH, {"data": []})

    with pytest.raises(RootCauseError) as exc:
        _twin(transport).group("APAC")

    assert "none saved yet" in str(exc.value)
    assert ".save(" in str(exc.value)


def test_group_membership_resolves_by_id_and_is_memoised(api, transport):
    api.on("POST", RESOLVE_PATH, RESOLVED_EU)
    group = Group(_twin(transport), dict(EU_GROUP))

    frame = group.environments
    combos = group.combos()

    assert list(frame["envKey"]) == ["london", "berlin"]
    assert list(frame["store"]) == ["london", "berlin"]
    assert frame.attrs["totalEnvCount"] == 3
    assert combos == [{"store": "london"}, {"store": "berlin"}]
    assert api.body_of("POST", "/environment-groups/resolve") == {"groupId": "grp-eu"}
    assert len(_paths(api, "/environment-groups/resolve")) == 1
    assert not _paths(api, "/environments/resolve")


def test_group_never_reads_the_environment_listing(api, transport):
    api.on("POST", RESOLVE_PATH, RESOLVED_EU)

    Group(_twin(transport), dict(EU_GROUP)).combos()

    assert _paths(api, f"{VERSION_PATH}/environments") == []
    assert _paths(api, RESOLVE_PATH) == [RESOLVE_PATH]


def test_unresolvable_group_raises_with_the_reason_on_access(api, transport):
    api.on("POST", RESOLVE_PATH, {"data": {
        "groupId": "grp-eu", "name": "EU stores",
        "environmentColumns": [], "environments": [], "envKeys": [],
        "sampleSize": 0, "totalEnvCount": 0, "unresolvedEnvCount": 0,
        "unresolvable": {
            "reason": "unknownEnvironmentColumn",
            "message": 'This version has no environment column "store"',
            "columns": ["store"],
        },
    }})
    group = Group(_twin(transport), dict(EU_GROUP))

    assert repr(group) == "Group('EU stores', id=grp-eu)"
    with pytest.raises(RootCauseError) as exc:
        group.combos()

    message = str(exc.value)
    assert "EU stores" in message
    assert "unknownEnvironmentColumn" in message
    assert 'no environment column "store"' in message
    assert "store" in message


def test_a_group_matching_nothing_is_not_an_error(api, transport):
    api.on("POST", RESOLVE_PATH, {"data": {
        "groupId": "grp-eu", "name": "EU stores",
        "environmentColumns": ["store"], "environments": [], "envKeys": [],
        "sampleSize": 0, "totalEnvCount": 3, "unresolvedEnvCount": 0, "unresolvable": None,
    }})
    group = Group(_twin(transport), dict(EU_GROUP))

    assert group.combos() == []
    assert group.environments.empty
    assert repr(group) == "Group('EU stores', environments=0)"


def test_group_repr_counts_members_once_resolved(api, transport):
    api.on("POST", RESOLVE_PATH, RESOLVED_EU)
    group = Group(_twin(transport), dict(EU_GROUP))
    group.combos()

    assert repr(group) == "Group('EU stores', environments=2)"


def test_group_adjacency_slices_on_the_resolved_combos(api, transport):
    api.on("POST", RESOLVE_PATH, RESOLVED_EU)
    api.on("POST", f"{VERSION_PATH}/graph/slice", {"data": {
        "causalGraph": [{"source": "price", "target": "demand", "strength": 0.9}],
        "nodes": [], "envCount": 2, "totalEnvCount": 3,
    }})

    frame = Group(_twin(transport), dict(EU_GROUP)).graph

    assert list(frame["source"]) == ["price"]
    assert frame.attrs["envCount"] == 2
    assert api.body_of("POST", "/graph/slice") == {
        "mode": "environments", "environments": [{"store": "london"}, {"store": "berlin"}],
    }


def test_group_intervene_names_the_group_instead_of_the_environments(api, transport):
    api.on("POST", f"/api/v1/workspaces/{WS}/simulations", {"data": {"runId": "r1"}})
    api.on("GET", f"/api/v1/workspaces/{WS}/simulations/r1", {"data": {"status": "completed"}})

    Group(_twin(transport), dict(EU_GROUP)).intervene(
        {"price": {"type": "percentage", "value": -10}}, outcomes=["revenue"]
    )

    body = api.body_of("POST", "/simulations")
    assert body["environmentGroupIds"] == ["grp-eu"]
    assert body["scenario"]["type"] == "panel_intervention"
    assert body["scenario"]["environments"] is None
    assert not _paths(api, "/environment-groups/resolve")


def test_group_forecast_names_the_group_instead_of_the_environments(api, transport):
    api.on("POST", f"/api/v1/workspaces/{WS}/simulations", {"data": {"runId": "r1"}})
    api.on("GET", f"/api/v1/workspaces/{WS}/simulations/r1", {"data": {"status": "completed"}})

    result = Group(_twin(transport), dict(EU_GROUP)).forecast(3, targets=["revenue"])

    body = api.body_of("POST", "/simulations")
    assert body["environmentGroupIds"] == ["grp-eu"]
    assert body["scenario"]["type"] == "panel_forecast"
    assert body["scenario"]["forecastH"] == 3
    assert body["scenario"]["environments"] is None
    assert result.run_id == "r1"
    assert not _paths(api, "/environment-groups/resolve")


def test_group_sample_falls_back_to_resolved_environment_names(api, transport):
    api.on("POST", RESOLVE_PATH, RESOLVED_EU)
    api.on("POST", f"{VERSION_PATH}/sample", {"data": {"draws": []}})

    Group(_twin(transport), dict(EU_GROUP)).sample(n=25)

    body = api.body_of("POST", "/sample")
    assert body["spec"]["environments"] == ["london", "berlin"]
    assert body["n"] == 25
    assert "environmentGroupIds" not in body


def test_temp_subsets_still_expand_to_environments(api, transport):
    api.on("GET", f"{VERSION_PATH}/environments", ENV_LISTING)
    api.on("POST", f"/api/v1/workspaces/{WS}/simulations", {"data": {"runId": "r1"}})
    api.on("GET", f"/api/v1/workspaces/{WS}/simulations/r1", {"data": {"status": "completed"}})

    _twin(transport).env("london").intervene(
        {"price": {"type": "percentage", "value": -10}}, outcomes=["revenue"]
    )

    body = api.body_of("POST", "/simulations")
    assert body["scenario"]["environments"] == ["london"]
    assert "environmentGroupIds" not in body


def test_rename_patches_the_name_and_keeps_the_handle(api, transport):
    api.on("PATCH", f"{GROUPS_PATH}/grp-eu", {"data": {**EU_GROUP, "name": "Eurozone"}})
    group = Group(_twin(transport), dict(EU_GROUP))

    same = group.rename("Eurozone")

    assert same is group
    assert group.name == "Eurozone"
    assert api.body_of("PATCH", "/environment-groups/grp-eu") == {"name": "Eurozone"}


def test_rename_collision_is_a_clear_error(api, transport):
    api.on("PATCH", f"{GROUPS_PATH}/grp-eu",
           {"title": "Conflict", "detail": 'A group named "High revenue" already exists'}, status=409)

    with pytest.raises(RootCauseError) as exc:
        Group(_twin(transport), dict(EU_GROUP)).rename("High revenue")

    assert "unique per twin" in str(exc.value)


def test_update_by_environment_names_replaces_the_definition(api, transport):
    api.on("GET", f"{VERSION_PATH}/environments", ENV_LISTING)
    updated = {**EU_GROUP, "definition": {
        "mode": "environments", "environments": [{"store": "london"}, {"store": "paris"}],
    }}
    api.on("PATCH", f"{GROUPS_PATH}/grp-eu", {"data": updated})

    group = Group(_twin(transport), dict(EU_GROUP))
    group.update("london", "paris")

    assert api.body_of("PATCH", "/environment-groups/grp-eu") == {
        "definition": {"mode": "environments", "environments": [{"store": "london"}, {"store": "paris"}]},
    }
    assert group.definition["environments"] == [{"store": "london"}, {"store": "paris"}]


def test_update_by_where_replaces_the_definition_with_stat_filters(api, transport):
    api.on("PATCH", f"{GROUPS_PATH}/grp-eu", {"data": {**EU_GROUP, "definition": BIG_GROUP["definition"]}})

    Group(_twin(transport), dict(EU_GROUP)).update(where=[("revenue", "avg", ">", 400)])

    assert api.body_of("PATCH", "/environment-groups/grp-eu") == {"definition": BIG_GROUP["definition"]}


def test_update_accepts_a_raw_definition(api, transport):
    definition = {"mode": "columnValues", "columnValues": {"store": ["london", "paris"]}}
    api.on("PATCH", f"{GROUPS_PATH}/grp-eu", {"data": {**EU_GROUP, "definition": definition}})

    Group(_twin(transport), dict(EU_GROUP)).update(definition=definition)

    assert api.body_of("PATCH", "/environment-groups/grp-eu") == {"definition": definition}


def test_update_needs_exactly_one_selection_style(api, transport):
    group = Group(_twin(transport), dict(EU_GROUP))
    with pytest.raises(RootCauseError):
        group.update()
    with pytest.raises(RootCauseError):
        group.update("london", where=[("revenue", "avg", ">", 400)])
    assert not api.requests


def test_update_drops_the_memoised_membership(api, transport):
    api.on("POST", RESOLVE_PATH, RESOLVED_EU)
    api.on("PATCH", f"{GROUPS_PATH}/grp-eu", {"data": EU_GROUP})
    group = Group(_twin(transport), dict(EU_GROUP))

    group.combos()
    group.update(definition=EU_GROUP["definition"])
    group.combos()

    assert len(_paths(api, "/environment-groups/resolve")) == 2


def test_delete_calls_the_group_endpoint(api, transport):
    api.on("DELETE", f"{GROUPS_PATH}/grp-eu", lambda request: httpx.Response(204))

    assert Group(_twin(transport), dict(EU_GROUP)).delete() is None
    assert _paths(api, "/environment-groups/grp-eu") == [f"{GROUPS_PATH}/grp-eu"]


def test_deleting_a_group_that_is_already_gone_is_a_no_op(api, transport):
    api.on("DELETE", f"{GROUPS_PATH}/grp-eu",
           {"title": "Not Found", "detail": "Environment group not found"}, status=404)

    assert Group(_twin(transport), dict(EU_GROUP)).delete() is None


def test_simulation_result_exposes_environment_group_snapshots(api, transport):
    snapshots = [
        {"id": "grp-eu", "name": "EU stores", "envKeys": ["london", "berlin"], "droppedEnvKeys": []},
        {"id": "grp-big", "name": "High revenue", "envKeys": ["london"],
         "droppedEnvKeys": ["madrid"], "notice": "1 environment is untrained on this version"},
    ]
    result = SimulationResult(transport, WS, "r1", {"status": "completed", "environmentGroupSnapshots": snapshots})

    assert result.environment_groups == snapshots
    assert result.environment_groups[1]["droppedEnvKeys"] == ["madrid"]


def test_simulation_result_environment_groups_is_empty_without_snapshots(api, transport):
    result = SimulationResult(transport, WS, "r1", {"status": "completed"})

    assert result.environment_groups == []


def test_group_link_points_at_the_twin(api, transport):
    api.on("GET", "/api/v1/me", {"data": {"organisationId": "org1"}})

    link = Group(_twin(transport), dict(EU_GROUP)).link()

    assert str(link) == "https://fake.rootcause.test/org1/space/ws1/twins/tw1?version=1.0.0"
