import pandas as pd
import pytest

from rootcause.direct import frame_fingerprint, infer_kind
from rootcause.errors import KindMismatchError


def test_kind_inference_matrix():
    assert infer_kind(None, None, None) == "static"
    assert infer_kind("month", None, None) == "temporal"
    assert infer_kind(None, "store", None) == "multi-environment-static"
    assert infer_kind("month", "store", None) == "multi-environment-temporal"


def test_explicit_kind_that_agrees_passes():
    assert infer_kind("month", None, "temporal") == "temporal"


@pytest.mark.parametrize(
    ("time", "entity", "kind"),
    [
        ("month", None, "static"),
        (None, None, "temporal"),
        ("month", "store", "temporal"),
        (None, "store", "multi-environment-temporal"),
    ],
)
def test_explicit_kind_mismatch_throws(time, entity, kind):
    with pytest.raises(KindMismatchError):
        infer_kind(time, entity, kind)


def test_unknown_kind_throws():
    with pytest.raises(KindMismatchError):
        infer_kind(None, None, "quantum")


def test_frame_fingerprint_deterministic_and_content_sensitive():
    frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    same = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    different = pd.DataFrame({"a": [1, 2, 4], "b": ["x", "y", "z"]})
    assert frame_fingerprint(frame) == frame_fingerprint(same)
    assert frame_fingerprint(frame) != frame_fingerprint(different)
    assert len(frame_fingerprint(frame)) == 12
