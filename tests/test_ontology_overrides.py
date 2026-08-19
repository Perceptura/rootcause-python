import json

import httpx
import pytest

from rootcause.errors import RootCauseError
from rootcause.ontology import Concept, Ontology

WS = "ws1"
BASE = f"/api/v1/workspaces/{WS}/ontology"

# The write path answers a status envelope, not a concept — the SDK must
# re-read after updating. Mocks mirror that shape so the tests can't pass on
# behaviour the real platform doesn't have.
PUT_ENVELOPE = {"data": {"status": "success", "message": "Concept updated"}}

CONCEPT = {
    "id": "c-rev",
    "name": "cumulative_revenue",
    "schemaType": "Number",
    "schemaFieldName": "cumulative_revenue",
    "editVersion": 3,
    "metadata": {"minValue": -50.0, "unit": None, "isMonotonicallyIncreasing": None},
    "detectedMetadata": None,
    "lockedMetadataFields": [],
    "fieldMappings": [],
}


def _stateful_get(api, before: dict, after: dict):
    """GET returns `before` until a PUT lands, then `after` — like a real server."""
    state = {"updated": False}

    def get_handler(request):
        return httpx.Response(200, json={"data": after if state["updated"] else before})

    def put_handler(request):
        state["updated"] = True
        return httpx.Response(200, json=PUT_ENVELOPE)

    concept_id = before.get("id")
    api.on("GET", f"{BASE}/concepts", {"data": [before]})
    api.on("GET", f"{BASE}/concepts/{concept_id}", get_handler)
    api.on("PUT", f"{BASE}/concepts/{concept_id}", put_handler)
    return state


def test_override_sends_only_changed_metadata_with_the_edit_version(api, transport):
    after = {**CONCEPT, "editVersion": 4,
             "metadata": {**CONCEPT["metadata"], "isMonotonicallyIncreasing": True, "minValue": 0},
             "lockedMetadataFields": ["isMonotonicallyIncreasing", "minValue"]}
    _stateful_get(api, CONCEPT, after)

    updated = Ontology(transport, WS).override(
        "cumulative_revenue", monotonically_increasing=True, min_value=0)

    body = api.body_of("PUT", "/concepts/c-rev")
    assert body["_id"] == "c-rev"
    assert body["editVersion"] == 3
    assert body["metadata"] == {"isMonotonicallyIncreasing": True, "minValue": 0}
    assert "name" not in body
    # the returned document is the post-update re-read, not the PUT envelope
    assert updated["lockedMetadataFields"] == ["isMonotonicallyIncreasing", "minValue"]
    assert updated["editVersion"] == 4


def test_override_concept_level_fields_travel_outside_metadata(api, transport):
    _stateful_get(api, CONCEPT, {**CONCEPT, "suggestedRole": "target"})

    updated = Ontology(transport, WS).override(
        "cumulative_revenue", suggested_role="target", description="Total booked revenue")

    body = api.body_of("PUT", "/concepts/c-rev")
    assert body["suggestedRole"] == "target"
    assert body["description"] == "Total booked revenue"
    assert "metadata" not in body
    assert updated["suggestedRole"] == "target"


def test_override_arbitrary_metadata_via_dict(api, transport):
    _stateful_get(api, CONCEPT, dict(CONCEPT))

    Ontology(transport, WS).override(
        "cumulative_revenue", metadata={"nanFillStrategy": "zero"}, unit="GBP")

    body = api.body_of("PUT", "/concepts/c-rev")
    assert body["metadata"] == {"nanFillStrategy": "zero", "unit": "GBP"}


def test_override_unknown_kwarg_lists_the_vocabulary(api, transport):
    api.on("GET", f"{BASE}/concepts", {"data": [dict(CONCEPT)]})
    with pytest.raises(RootCauseError) as exc:
        Ontology(transport, WS).override("cumulative_revenue", monotonic=True)
    assert "monotonic" in str(exc.value)
    assert "monotonically_increasing" in str(exc.value)


def test_override_nothing_is_an_error(api, transport):
    api.on("GET", f"{BASE}/concepts", {"data": [dict(CONCEPT)]})
    with pytest.raises(RootCauseError):
        Ontology(transport, WS).override("cumulative_revenue")


def test_stale_edit_version_retries_once_with_a_fresh_read(api, transport):
    doc = dict(CONCEPT)
    api.on("GET", f"{BASE}/concepts", {"data": [doc]})
    reads = {"n": 0}

    def get_handler(request):
        reads["n"] += 1
        version = {1: 3, 2: 7}.get(reads["n"], 8)
        return httpx.Response(200, json={"data": {**doc, "editVersion": version}})

    api.on("GET", f"{BASE}/concepts/c-rev", get_handler)

    attempts = []

    def put_handler(request):
        body = json.loads(request.content.decode())
        attempts.append(body["editVersion"])
        if len(attempts) == 1:
            return httpx.Response(409, json={"title": "Conflict", "status": 409, "detail": "updated elsewhere"})
        return httpx.Response(200, json=PUT_ENVELOPE)

    api.on("PUT", f"{BASE}/concepts/c-rev", put_handler)

    updated = Ontology(transport, WS).override("cumulative_revenue", unit="GBP")

    assert attempts == [3, 7]
    assert updated["editVersion"] == 8


def test_revert_restores_detected_values_for_locked_fields(api, transport):
    overridden = {
        **CONCEPT,
        "metadata": {"minValue": 0, "isMonotonicallyIncreasing": True, "unit": "GBP"},
        "detectedMetadata": {"minValue": -50.0, "isMonotonicallyIncreasing": None, "unit": None},
        "lockedMetadataFields": ["isMonotonicallyIncreasing", "minValue"],
    }
    _stateful_get(api, overridden, {**overridden, "lockedMetadataFields": []})

    updated = Ontology(transport, WS).revert("cumulative_revenue")

    body = api.body_of("PUT", "/concepts/c-rev")
    assert body["metadata"] == {"isMonotonicallyIncreasing": None, "minValue": -50.0}
    assert updated["lockedMetadataFields"] == []


def test_revert_accepts_snake_case_field_names(api, transport):
    overridden = {
        **CONCEPT,
        "detectedMetadata": {"minValue": -50.0, "isMonotonicallyIncreasing": None},
        "lockedMetadataFields": ["isMonotonicallyIncreasing", "minValue"],
    }
    _stateful_get(api, overridden, dict(overridden))

    Ontology(transport, WS).revert("cumulative_revenue", "monotonically_increasing")

    body = api.body_of("PUT", "/concepts/c-rev")
    assert body["metadata"] == {"isMonotonicallyIncreasing": None}


def test_revert_without_detected_metadata_is_a_clear_error(api, transport):
    doc = dict(CONCEPT)
    api.on("GET", f"{BASE}/concepts", {"data": [doc]})
    api.on("GET", f"{BASE}/concepts/c-rev", {"data": doc})
    with pytest.raises(RootCauseError) as exc:
        Ontology(transport, WS).revert("cumulative_revenue")
    assert "detected" in str(exc.value)


def test_revert_unlocked_field_is_a_clear_error(api, transport):
    overridden = {**CONCEPT, "detectedMetadata": {"unit": None}, "lockedMetadataFields": ["unit"]}
    api.on("GET", f"{BASE}/concepts", {"data": [overridden]})
    api.on("GET", f"{BASE}/concepts/c-rev", {"data": overridden})
    with pytest.raises(RootCauseError) as exc:
        Ontology(transport, WS).revert("cumulative_revenue", "min_value")
    assert "minValue" in str(exc.value)


def test_locks_frame_shows_value_vs_detected(api, transport):
    overridden = {
        **CONCEPT,
        "metadata": {"minValue": 0, "unit": "GBP"},
        "detectedMetadata": {"minValue": -50.0, "unit": None},
        "lockedMetadataFields": ["minValue"],
    }
    api.on("GET", f"{BASE}/concepts", {"data": [overridden]})
    api.on("GET", f"{BASE}/concepts/c-rev", {"data": overridden})

    frame = Ontology(transport, WS).locks("cumulative_revenue")

    assert list(frame["field"]) == ["minValue"]
    assert list(frame["value"]) == [0]
    assert list(frame["detected"]) == [-50.0]


def test_ambiguous_concept_name_refuses_and_lists_candidates(api, transport):
    twins = [
        {**CONCEPT, "id": "c-rev-a", "schemaFieldName": "revenue", "fieldMappings": [{}]},
        {**CONCEPT, "id": "c-rev-b", "schemaFieldName": "total_revenue", "fieldMappings": [{}, {}]},
    ]
    api.on("GET", f"{BASE}/concepts", {"data": twins})

    with pytest.raises(RootCauseError) as exc:
        Ontology(transport, WS).override("cumulative_revenue", unit="GBP")

    message = str(exc.value)
    assert "2 concepts" in message
    assert "c-rev-a" in message and "c-rev-b" in message
    assert "total_revenue" in message


def test_ambiguous_name_still_resolves_by_exact_id(api, transport):
    twins = [
        {**CONCEPT, "id": "c-rev-a"},
        {**CONCEPT, "id": "c-rev-b"},
    ]
    api.on("GET", f"{BASE}/concepts", {"data": twins})
    api.on("GET", f"{BASE}/concepts/c-rev-b", {"data": twins[1]})
    api.on("PUT", f"{BASE}/concepts/c-rev-b", PUT_ENVELOPE)

    Ontology(transport, WS).override("c-rev-b", unit="GBP")

    body = api.body_of("PUT", "/concepts/c-rev-b")
    assert body["_id"] == "c-rev-b"


def test_concept_handle_flow_never_touches_names_again(api, transport):
    after = {**CONCEPT, "editVersion": 4, "lockedMetadataFields": ["unit"],
             "metadata": {**CONCEPT["metadata"], "unit": "GBP"}}
    _stateful_get(api, CONCEPT, after)

    concept = Ontology(transport, WS)["cumulative_revenue"]
    assert isinstance(concept, Concept)
    assert concept["schemaType"] == "Number"  # dict-style access still works

    same = concept.override(unit="GBP")
    assert same is concept
    assert concept.doc["lockedMetadataFields"] == ["unit"]
    assert concept.metadata["unit"] == "GBP"
    assert repr(concept) == "Concept('cumulative_revenue', type=Number, overrides=1)"


def test_matching_disambiguates_into_handles(api, transport):
    docs = [
        {**CONCEPT, "id": "c-rev-a", "schemaFieldName": "revenue"},
        {**CONCEPT, "id": "c-rev-b", "schemaFieldName": "total_revenue"},
    ]
    api.on("GET", f"{BASE}/concepts", {"data": docs})
    onto = Ontology(transport, WS)

    matches = onto.matching("cumulative_revenue")
    assert [c.id for c in matches] == ["c-rev-a", "c-rev-b"]

    api.on("GET", f"{BASE}/concepts/c-rev-b", {"data": docs[1]})
    api.on("PUT", f"{BASE}/concepts/c-rev-b", PUT_ENVELOPE)
    matches[1].override(unit="GBP")
    assert api.body_of("PUT", "/concepts/c-rev-b")["_id"] == "c-rev-b"


def test_concept_revert_and_locks_on_the_handle(api, transport):
    overridden = {
        **CONCEPT,
        "metadata": {"unit": "GBP"},
        "detectedMetadata": {"unit": None},
        "lockedMetadataFields": ["unit"],
    }
    _stateful_get(api, overridden, {**overridden, "lockedMetadataFields": [], "metadata": {"unit": None}})

    concept = Ontology(transport, WS)["cumulative_revenue"]
    frame = concept.locks
    assert list(frame["field"]) == ["unit"]

    concept.revert()
    assert concept.doc["lockedMetadataFields"] == []
