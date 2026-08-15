import httpx
import pytest

from rootcause._http import Transport
from rootcause.errors import RootCauseApiError


def test_problem_json_maps_to_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"title": "Forbidden", "status": 403, "detail": "API key missing required scope(s): ontology:read"})

    transport = Transport("https://fake.test", "pk_x", httpx_transport=httpx.MockTransport(handler))
    with pytest.raises(RootCauseApiError) as exc:
        transport.request("GET", "/api/v1/workspaces")
    assert exc.value.status == 403
    assert "ontology:read" in exc.value.detail


def test_retry_on_429_honours_retry_after(monkeypatch: pytest.MonkeyPatch):
    sleeps: list[float] = []
    monkeypatch.setattr("rootcause._http.time.sleep", sleeps.append)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, json={"detail": "slow down"})
        return httpx.Response(200, json={"data": []})

    transport = Transport("https://fake.test", "pk_x", httpx_transport=httpx.MockTransport(handler))
    assert transport.request("GET", "/api/v1/workspaces") == {"data": []}
    assert calls["n"] == 2
    assert sleeps == [7.0]


def test_non_retryable_4xx_does_not_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, json={"title": "Not Found", "status": 404, "detail": "nope"})

    transport = Transport("https://fake.test", "pk_x", httpx_transport=httpx.MockTransport(handler))
    with pytest.raises(RootCauseApiError):
        transport.request("GET", "/api/v1/workspaces/x")
    assert calls["n"] == 1


def test_bearer_header_sent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={})

    transport = Transport("https://fake.test", "pk_secret", httpx_transport=httpx.MockTransport(handler))
    transport.request("GET", "/api/v1/workspaces")
    assert seen["auth"] == "Bearer pk_secret"
