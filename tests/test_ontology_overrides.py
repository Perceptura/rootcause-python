import pytest

from rootcause.errors import RootCauseError
from rootcause.ontology import Ontology

WS = "ws1"
BASE = f"/api/v1/workspaces/{WS}/ontology"

CONCEPT = {
    "id": "c-rev",
    "name": "cumulative_revenue",
    "schemaType": "Number",
    "editVersion": 3,
    "metadata": {"minValue": -50.0, "unit": None, "isMonotonicallyIncreasing": None},
    "detectedMetadata": None,
    "lockedMetadataFields": [],
    "fieldMappings": [],
}


def _onto(api, transport, concept=None) -> Ontology:
    doc = dict(concept or CONCEPT)
    api.on("GET", f"{BASE}/concepts", {"data": [doc]})
    api.on("GET", f"{BASE}/concepts/c-rev", {"data": doc})
    return Ontology(transport, WS)


def test_override_sends_only_changed_metadata_with_the_edit_version(api, transport):
    onto = _onto(api, transport)
    api.on("PUT", f"{BASE}/concepts/c-rev", {"data": {**CONCEPT, "editVersion": 4,
        "metadata": {**CONCEPT["metadata"], "isMonotonicallyIncreasing": True, "minValue": 0},
        "lockedMetadataFields": ["isMonotonicallyIncreasing", "minValue"]}})

    updated = onto.override("cumulative_revenue", monotonically_increasing=True, min_value=0)

    body = api.body_of("PUT", "/concepts/c-rev")
    assert body["_id"] == "c-rev"
    assert body["editVersion"] == 3
    assert body["metadata"] == {"isMonotonicallyIncreasing": True, "minValue": 0}
    assert "name" not in body
    assert updated["lockedMetadataFields"] == ["isMonotonicallyIncreasing", "minValue"]


def test_override_concept_level_fields_travel_outside_metadata(api, transport):
    onto = _onto(api, transport)
    api.on("PUT", f"{BASE}/concepts/c-rev", {"data": {**CONCEPT, "suggestedRole": "target"}})

    onto.override("cumulative_revenue", suggested_role="target", description="Total booked revenue")

    body = api.body_of("PUT", "/concepts/c-rev")
    assert body["suggestedRole"] == "target"
    assert body["description"] == "Total booked revenue"
    assert "metadata" not in body


def test_override_arbitrary_metadata_via_dict(api, transport):
    onto = _onto(api, transport)
    api.on("PUT", f"{BASE}/concepts/c-rev", {"data": dict(CONCEPT)})

    onto.override("cumulative_revenue", metadata={"nanFillStrategy": "zero"}, unit="GBP")

    body = api.body_of("PUT", "/concepts/c-rev")
    assert body["metadata"] == {"nanFillStrategy": "zero", "unit": "GBP"}


def test_override_unknown_kwarg_lists_the_vocabulary(api, transport):
    onto = _onto(api, transport)
    with pytest.raises(RootCauseError) as exc:
        onto.override("cumulative_revenue", monotonic=True)
    assert "monotonic" in str(exc.value)
    assert "monotonically_increasing" in str(exc.value)


def test_override_nothing_is_an_error(api, transport):
    onto = _onto(api, transport)
    with pytest.raises(RootCauseError):
        onto.override("cumulative_revenue")


def test_stale_edit_version_retries_once_with_a_fresh_read(api, transport):
    import httpx

    doc = dict(CONCEPT)
    api.on("GET", f"{BASE}/concepts", {"data": [doc]})
    reads = {"n": 0}

    def get_handler(request):
        reads["n"] += 1
        return httpx.Response(200, json={"data": {**doc, "editVersion": 3 if reads["n"] == 1 else 7}})

    api.on("GET", f"{BASE}/concepts/c-rev", get_handler)

    attempts = []

    def put_handler(request):
        import json

        body = json.loads(request.content.decode())
        attempts.append(body["editVersion"])
        if len(attempts) == 1:
            return httpx.Response(409, json={"title": "Conflict", "status": 409, "detail": "updated elsewhere"})
        return httpx.Response(200, json={"data": {**doc, "editVersion": 8}})

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
    onto = _onto(api, transport, overridden)
    api.on("PUT", f"{BASE}/concepts/c-rev", {"data": {**overridden, "lockedMetadataFields": []}})

    onto.revert("cumulative_revenue")

    body = api.body_of("PUT", "/concepts/c-rev")
    assert body["metadata"] == {"isMonotonicallyIncreasing": None, "minValue": -50.0}


def test_revert_accepts_snake_case_field_names(api, transport):
    overridden = {
        **CONCEPT,
        "detectedMetadata": {"minValue": -50.0, "isMonotonicallyIncreasing": None},
        "lockedMetadataFields": ["isMonotonicallyIncreasing", "minValue"],
    }
    onto = _onto(api, transport, overridden)
    api.on("PUT", f"{BASE}/concepts/c-rev", {"data": dict(overridden)})

    onto.revert("cumulative_revenue", "monotonically_increasing")

    body = api.body_of("PUT", "/concepts/c-rev")
    assert body["metadata"] == {"isMonotonicallyIncreasing": None}


def test_revert_without_detected_metadata_is_a_clear_error(api, transport):
    onto = _onto(api, transport)
    with pytest.raises(RootCauseError) as exc:
        onto.revert("cumulative_revenue")
    assert "detected" in str(exc.value)


def test_revert_unlocked_field_is_a_clear_error(api, transport):
    overridden = {**CONCEPT, "detectedMetadata": {"unit": None}, "lockedMetadataFields": ["unit"]}
    onto = _onto(api, transport, overridden)
    with pytest.raises(RootCauseError) as exc:
        onto.revert("cumulative_revenue", "min_value")
    assert "minValue" in str(exc.value)


def test_locks_frame_shows_value_vs_detected(api, transport):
    overridden = {
        **CONCEPT,
        "metadata": {"minValue": 0, "unit": "GBP"},
        "detectedMetadata": {"minValue": -50.0, "unit": None},
        "lockedMetadataFields": ["minValue"],
    }
    onto = _onto(api, transport, overridden)

    frame = onto.locks("cumulative_revenue")

    assert list(frame["field"]) == ["minValue"]
    assert list(frame["value"]) == [0]
    assert list(frame["detected"]) == [-50.0]


def test_ambiguous_concept_name_refuses_and_lists_candidates(api, transport):
    twins = [
        {**CONCEPT, "id": "c-rev-a", "schemaFieldName": "revenue", "fieldMappings": [{}]},
        {**CONCEPT, "id": "c-rev-b", "schemaFieldName": "total_revenue", "fieldMappings": [{}, {}]},
    ]
    api.on("GET", f"{BASE}/concepts", {"data": twins})
    onto = Ontology(transport, WS)

    with pytest.raises(RootCauseError) as exc:
        onto.override("cumulative_revenue", unit="GBP")

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
    api.on("PUT", f"{BASE}/concepts/c-rev-b", {"data": twins[1]})

    Ontology(transport, WS).override("c-rev-b", unit="GBP")

    body = api.body_of("PUT", "/concepts/c-rev-b")
    assert body["_id"] == "c-rev-b"
