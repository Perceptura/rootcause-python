"""Error messages must be readable and suggest the fix — the fixtures below are
real garbage the platform has produced, verbatim."""

import pytest

from rootcause.errors import JobFailedError, RootCauseApiError


def test_html_404_becomes_a_deployment_hint_not_a_page_dump():
    html = '<!DOCTYPE html><html lang="en"><head><meta charSet="utf-8"/>' + "<script>" * 400
    error = RootCauseApiError.from_response({"detail": html}, 404)

    message = str(error)
    assert "<!DOCTYPE" not in message
    assert "script" not in message
    assert "does not exist on that deployment" in message
    assert "older than this SDK" in message
    assert len(message) < 400


def test_html_5xx_is_summarised_without_the_page():
    error = RootCauseApiError.from_response({"detail": "<html><body>Internal error</body></html>"}, 502)
    assert "<html>" not in str(error)
    assert "502" in str(error)


def test_embedded_upstream_stack_trace_is_condensed_to_the_human_fields():
    upstream = (
        'Upstream error: 500 — {"type":"http://127.0.0.1:8003/error/internal-server-error",'
        '"status":500,"title":"Internal Server Error","detail":"Pipeline run not found",'
        '"resource":"Pipeline run","traceId":"e3a3ef48c414e800",'
        '"stack":"Traceback (most recent call last):\\n  File \\"C:\\\\x.py\\", line 1"}'
    )
    error = RootCauseApiError.from_response({"detail": upstream, "title": "Internal Server Error"}, 500)

    message = str(error)
    assert "Traceback" not in message
    assert "Pipeline run not found" in message
    assert "traceId: e3a3ef48c414e800" in message
    assert "resource: Pipeline run" in message


def test_401_suggests_relogin():
    error = RootCauseApiError.from_response({"title": "Unauthorized", "detail": "Invalid API key"}, 401)
    assert "rc.login()" in str(error)
    assert "ROOTCAUSE_API_KEY" in str(error)


def test_403_points_at_scopes_and_whoami():
    error = RootCauseApiError.from_response({"title": "Forbidden", "detail": "Missing scope sources:write"}, 403)
    message = str(error)
    assert "Missing scope sources:write" in message
    assert "rc.whoami()" in message


def test_429_explains_the_retry_behaviour():
    error = RootCauseApiError.from_response({"title": "Too Many Requests", "detail": "slow down"}, 429)
    assert "retries these automatically" in str(error)


def test_ordinary_api_errors_stay_verbatim():
    error = RootCauseApiError.from_response({"title": "Not Found", "detail": "Twin not found"}, 404)
    assert str(error).startswith("[404 Not Found] Twin not found")


def test_very_long_details_are_truncated():
    error = RootCauseApiError.from_response({"detail": "x" * 5000}, 400)
    assert len(str(error)) < 700
    assert "[truncated]" in str(error)


def test_job_failure_formats_the_error_context_not_the_raw_dict():
    error = JobFailedError("mt-run-1", "failed", {
        "message": "twin type 'multi-environment-temporal' does not support incremental updates",
        "stepId": None,
        "errorType": "retrain_required",
        "retryable": False,
        "userFacing": False,
        "detail": None,
    })

    message = str(error)
    assert "'stepId': None" not in message
    assert "userFacing" not in message
    assert "does not support incremental updates" in message
    assert "[retrain_required]" in message
    assert error.error["errorType"] == "retrain_required"


def test_job_failure_keeps_step_and_hides_unknown_type():
    error = JobFailedError("cd-run-1", "failed", {
        "message": "boom", "errorType": "unknown", "stepId": "discovery",
    })
    message = str(error)
    assert "boom" in message and "(step discovery)" in message
    assert "unknown" not in message


def test_job_failure_with_plain_string_unchanged():
    assert str(JobFailedError("j1", "cancelled", "Cancelled by user")).endswith("Cancelled by user")
