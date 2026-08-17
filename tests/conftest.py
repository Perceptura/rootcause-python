import json
import re
from typing import Any, Callable

import httpx
import pytest

from rootcause._http import Transport

Handler = Callable[[httpx.Request], httpx.Response]


class FakeApi:
    """Route table for a mocked platform: exact 'METHOD path' keys or regex fallbacks."""

    def __init__(self) -> None:
        self.routes: dict[str, Any] = {}
        self.regex_routes: list[tuple[str, re.Pattern[str], Any]] = []
        self.requests: list[httpx.Request] = []

    def on(self, method: str, path: str, response: Any, status: int = 200) -> None:
        self.routes[f"{method} {path}"] = (response, status)

    def on_regex(self, method: str, pattern: str, response: Any, status: int = 200) -> None:
        self.regex_routes.append((method, re.compile(pattern), (response, status)))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.path}"
        entry = self.routes.get(key)
        if entry is None:
            for method, pattern, candidate in self.regex_routes:
                if method == request.method and pattern.fullmatch(request.url.path):
                    entry = candidate
                    break
        if entry is None:
            return httpx.Response(404, json={"title": "Not Found", "status": 404, "detail": f"no fake route for {key}"})
        response, status = entry
        if callable(response):
            return response(request)
        return httpx.Response(status, json=response)

    def body_of(self, method: str, path_contains: str) -> dict[str, Any]:
        for request in self.requests:
            if request.method == method and path_contains in request.url.path:
                return json.loads(request.content.decode())
        raise AssertionError(f"no captured {method} request containing {path_contains}")


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def transport(api: FakeApi) -> Transport:
    return Transport(
        "https://fake.rootcause.test",
        "pk_test",
        httpx_transport=httpx.MockTransport(api.handler),
    )
