import base64
import hashlib
import json
import os
import secrets
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from rootcause.errors import (
    AuthenticationError,
    JobFailedError,
    JobTimeoutError,
    RootCauseApiError,
)

DEFAULT_BASE_URL = "https://platform.rootcause.ai"
CREDENTIALS_PATH = Path.home() / ".rootcause" / "credentials.json"
RETRYABLE_STATUSES = {429, 502, 503, 504}
JOB_TERMINAL = {"completed", "failed", "cancelled"}
RUN_TERMINAL = {"completed", "failed", "cancelled"}


def _read_credentials() -> dict[str, Any]:
    try:
        return json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_credentials(store: dict[str, Any]) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")
    try:
        CREDENTIALS_PATH.chmod(0o600)
    except OSError:
        pass


class _OAuthSession:
    """Authorization-code + PKCE against the platform's OAuth server.

    Registers the SDK as a public client via dynamic client registration, opens
    the browser for consent, and falls back to paste-the-code when no local
    callback is reachable (remote kernels)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def login(self) -> dict[str, Any]:
        client_id = self._register_client()
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        redirect_uri, wait_for_code = self._callback()

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": secrets.token_urlsafe(16),
            "resource": f"{self.base_url}/api/v1",
        }
        url = f"{self.base_url}/api/oauth/authorize?{urlencode(params)}"
        print(f"Opening browser for RootCause login…\n  {url}", file=sys.stderr)
        webbrowser.open(url)
        code = wait_for_code()

        with httpx.Client(timeout=30.0) as http:
            resp = http.post(
                f"{self.base_url}/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "resource": f"{self.base_url}/api/v1",
                },
            )
        if resp.status_code >= 400:
            raise AuthenticationError(f"Token exchange failed ({resp.status_code}): {resp.text[:300]}")
        token = resp.json()
        return {
            "client_id": client_id,
            "access_token": token["access_token"],
            "refresh_token": token.get("refresh_token"),
            "expires_at": time.time() + float(token.get("expires_in", 3600)),
        }

    def refresh(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        if not entry.get("refresh_token"):
            return None
        with httpx.Client(timeout=30.0) as http:
            resp = http.post(
                f"{self.base_url}/api/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": entry["refresh_token"],
                    "client_id": entry["client_id"],
                    "resource": f"{self.base_url}/api/v1",
                },
            )
        if resp.status_code >= 400:
            return None
        token = resp.json()
        return {
            **entry,
            "access_token": token["access_token"],
            "refresh_token": token.get("refresh_token", entry["refresh_token"]),
            "expires_at": time.time() + float(token.get("expires_in", 3600)),
        }

    def _register_client(self) -> str:
        with httpx.Client(timeout=30.0) as http:
            resp = http.post(
                f"{self.base_url}/api/oauth/register",
                json={
                    "client_name": "rootcause-sdk",
                    "redirect_uris": ["http://127.0.0.1:8765/callback", "urn:ietf:wg:oauth:2.0:oob"],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "none",
                },
            )
        if resp.status_code >= 400:
            raise AuthenticationError(
                "Could not register the SDK as an OAuth client "
                f"({resp.status_code}). Use an API key instead: rc.login(api_key='pk_…') "
                "or set ROOTCAUSE_API_KEY."
            )
        return str(resp.json()["client_id"])

    def _callback(self) -> tuple[str, Callable[[], str]]:
        try:
            from http.server import BaseHTTPRequestHandler, HTTPServer

            holder: dict[str, str] = {}

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    from urllib.parse import parse_qs, urlparse

                    qs = parse_qs(urlparse(self.path).query)
                    holder["code"] = qs.get("code", [""])[0]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<h3>Login complete. You can close this tab.</h3>")

                def log_message(self, *args):
                    pass

            server = HTTPServer(("127.0.0.1", 8765), Handler)

            def wait() -> str:
                server.timeout = 300
                while "code" not in holder:
                    server.handle_request()
                server.server_close()
                if not holder["code"]:
                    raise AuthenticationError("Browser login returned no authorization code")
                return holder["code"]

            return "http://127.0.0.1:8765/callback", wait
        except OSError:
            def wait_paste() -> str:
                code = input("Paste the authorization code shown in the browser: ").strip()
                if not code:
                    raise AuthenticationError("No authorization code provided")
                return code

            return "urn:ietf:wg:oauth:2.0:oob", wait_paste


class Transport:
    """Synchronous HTTP layer: auth header, retries with backoff, problem+json mapping."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        oauth_entry: dict[str, Any] | None = None,
        timeout: float = 120.0,
        httpx_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._oauth_entry = oauth_entry
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, transport=httpx_transport)

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        max_attempts: int = 4,
    ) -> Any:
        response = self._raw(method, path, json_body=json_body, content=content, headers=headers, params=params, max_attempts=max_attempts)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def request_bytes(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> bytes:
        return self._raw(method, path, params=params).content

    def _raw(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        max_attempts: int = 4,
    ) -> httpx.Response:
        attempt = 0
        while True:
            attempt += 1
            all_headers = {"Authorization": f"Bearer {self._access_token()}", **(headers or {})}
            try:
                response = self._client.request(
                    method, path, json=json_body, content=content, headers=all_headers, params=params
                )
            except httpx.TransportError:
                if method == "GET" and attempt < max_attempts:
                    time.sleep(min(2.0 ** attempt, 20.0))
                    continue
                raise
            if response.status_code in RETRYABLE_STATUSES and attempt < max_attempts:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2.0 ** attempt, 20.0)
                time.sleep(delay)
                continue
            if response.status_code >= 400:
                try:
                    body = response.json()
                except (json.JSONDecodeError, ValueError):
                    body = {"detail": response.text}
                raise RootCauseApiError.from_response(body, response.status_code)
            return response

    def _access_token(self) -> str:
        entry = self._oauth_entry
        if entry is None:
            return self._token
        if time.time() > float(entry.get("expires_at", 0)) - 60:
            refreshed = _OAuthSession(self.base_url).refresh(entry)
            if refreshed is None:
                raise AuthenticationError("OAuth token expired and refresh failed; run rc.login() again")
            entry.update(refreshed)
            store = _read_credentials()
            store[self.base_url] = entry
            _write_credentials(store)
        return str(entry["access_token"])


def resolve_transport(api_key: str | None = None, base_url: str | None = None) -> Transport:
    """Credential resolution: explicit key → env → cached OAuth token → interactive PKCE."""
    resolved_base = (base_url or os.environ.get("ROOTCAUSE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")

    key = api_key or os.environ.get("ROOTCAUSE_API_KEY")
    if key:
        return Transport(resolved_base, key)

    store = _read_credentials()
    entry = store.get(resolved_base)
    if isinstance(entry, dict) and entry.get("access_token"):
        return Transport(resolved_base, "", oauth_entry=entry)

    session = _OAuthSession(resolved_base)
    entry = session.login()
    store[resolved_base] = entry
    _write_credentials(store)
    return Transport(resolved_base, "", oauth_entry=entry)


class _Progress:
    def __init__(self, label: str) -> None:
        self.label = label
        self._last = ""

    def update(self, status: str, progress: Any = None) -> None:
        pct = f" {progress}%" if isinstance(progress, (int, float)) else ""
        line = f"{self.label}: {status}{pct}"
        if line != self._last and sys.stderr.isatty():
            print(f"\r{line}    ", end="", file=sys.stderr, flush=True)
            self._last = line

    def done(self) -> None:
        if self._last and sys.stderr.isatty():
            print(file=sys.stderr)


def poll_job(
    transport: Transport,
    workspace_id: str,
    job_id: str,
    *,
    label: str = "job",
    interval: float = 3.0,
    timeout: float = 3600.0,
) -> dict[str, Any]:
    """Block until a pipeline job reaches a terminal state, drawing a progress line."""
    progress = _Progress(label)
    deadline = time.monotonic() + timeout
    # A freshly dispatched job can answer 404 for a beat while the run document
    # materialises; treat that as pending for a short grace window.
    grace_deadline = time.monotonic() + 30.0
    while True:
        try:
            doc = transport.request("GET", f"/api/v1/workspaces/{workspace_id}/jobs/{job_id}").get("data", {})
        except RootCauseApiError as error:
            if error.status == 404 and time.monotonic() < grace_deadline:
                progress.update("registering")
                time.sleep(interval)
                continue
            raise
        status = str(doc.get("status", "unknown"))
        progress.update(status, doc.get("progress"))
        if status in JOB_TERMINAL:
            progress.done()
            if status != "completed":
                raise JobFailedError(job_id, status, doc.get("error") or doc.get("message") or None)
            return doc
        if time.monotonic() > deadline:
            progress.done()
            raise JobTimeoutError(f"Job {job_id} still '{status}' after {timeout:.0f}s")
        time.sleep(interval)


def poll_run(
    transport: Transport,
    workspace_id: str,
    run_id: str,
    *,
    label: str = "simulation",
    interval: float = 3.0,
    timeout: float = 3600.0,
) -> dict[str, Any]:
    """Block until a simulation run reaches a terminal state."""
    progress = _Progress(label)
    deadline = time.monotonic() + timeout
    while True:
        doc = transport.request("GET", f"/api/v1/workspaces/{workspace_id}/simulations/{run_id}").get("data", {})
        status = str(doc.get("status", "unknown"))
        progress.update(status, doc.get("progress"))
        if status in RUN_TERMINAL:
            progress.done()
            if status != "completed":
                raise JobFailedError(run_id, status, doc.get("error") or None)
            return doc
        if time.monotonic() > deadline:
            progress.done()
            raise JobTimeoutError(f"Run {run_id} still '{status}' after {timeout:.0f}s")
        time.sleep(interval)
