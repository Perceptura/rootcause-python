"""Exception hierarchy for the SDK; every error derives from RootCauseError."""

from typing import Any


class RootCauseError(Exception):
    """Base class for every error this SDK raises."""


class AuthenticationError(RootCauseError):
    """No usable credentials, or the platform rejected the ones provided."""


class ConnectionFailedError(RootCauseError):
    """The platform could not be reached: DNS, TLS, refused connection, or a timeout."""


class MalformedResponseError(RootCauseError):
    """The platform answered, but not with the shape this SDK needs."""


class MissingDependencyError(RootCauseError, ImportError):
    """An optional extra this call needs is not installed; the message names it."""


class InvalidArgumentError(RootCauseError, ValueError):
    """An argument could not be used as passed, caught before any request went out."""


_STATUS_HINTS = {
    401: "Check the API key (ROOTCAUSE_API_KEY) or run rc.login() again.",
    403: "The credential lacks a scope for this operation — rc.whoami() shows what it carries.",
    404: "The object may have been deleted, or it lives in another workspace.",
    409: "The resource changed underneath this call — re-read it and retry.",
    413: "The payload is too large for one request — upload in batches with source.extend().",
    429: "Rate limited. The SDK retries these automatically; sustained 429s mean the key's per-minute limit is too low for this workload.",
    500: "A platform-side fault. Retrying rarely helps; quote the traceId to support.",
}

_MAX_DETAIL = 600


def _looks_like_html(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    return head.startswith("<!doctype") or head.startswith("<html")


def _condense_detail(detail: str, status: int) -> "tuple[str, bool]":
    """Readable server explanations — no HTML pages, no stacks — and whether the status hint still applies."""
    if _looks_like_html(detail):
        if status == 404:
            return (
                "The server answered with a web page, not an API response — this endpoint "
                "does not exist on that deployment. The platform is likely older than this "
                "SDK; check the base_url or update the platform."
            ), False
        return f"The server answered with a web page, not an API response (HTTP {status}).", False
    # A proxied upstream problem sometimes arrives embedded as JSON text, stack
    # trace and all; keep its human fields and the traceId, drop the trace.
    brace = detail.find("{")
    if brace != -1 and '"stack"' in detail:
        import json as _json

        try:
            upstream = _json.loads(detail[brace:])
        except ValueError:
            upstream = None
        if isinstance(upstream, dict):
            parts = [str(upstream.get("detail") or upstream.get("title") or "upstream error")]
            if upstream.get("resource"):
                parts.append(f'resource: {upstream["resource"]}')
            if upstream.get("traceId"):
                parts.append(f'traceId: {upstream["traceId"]}')
            return f"{detail[:brace].strip()} {' — '.join(parts)}".strip(), True
    if len(detail) > _MAX_DETAIL:
        return detail[:_MAX_DETAIL] + " … [truncated]", True
    return detail, True


class RootCauseApiError(RootCauseError):
    """The API answered with a problem response.

    Attributes:
        status (int): HTTP status code.
        title (str): Short problem title from the API.
        detail (str): The API's explanation, condensed to stay readable.
        body (Any): The raw problem body, when it was JSON.
    """

    def __init__(self, status: int, title: str, detail: str, body: Any = None, status_hint: bool = True) -> None:
        self.status = status
        self.title = title
        self.detail = detail
        self.body = body
        hint = _STATUS_HINTS.get(status) if status_hint else None
        message = f"[{status} {title}] {detail}"
        if hint:
            message = f"{message}\n{hint}"
        super().__init__(message)

    @classmethod
    def from_response(cls, body: Any, status: int) -> "RootCauseApiError":
        if isinstance(body, dict):
            title = str(body.get("title") or body.get("error") or "Error")
            detail = str(body.get("detail") or body.get("error") or body)
        else:
            title, detail = "Error", str(body)
        condensed, keep_hint = _condense_detail(detail, status)
        return cls(status, title, condensed, body, status_hint=keep_hint)


def _format_job_error(error: "str | dict | None") -> str:
    """A run's error context, without the raw-dict noise of its empty fields."""
    if not isinstance(error, dict):
        return str(error)
    parts = [str(error.get("message") or error.get("detail") or "unknown error")]
    error_type = error.get("errorType")
    if error_type and error_type != "unknown":
        parts.append(f"[{error_type}]")
    step = error.get("stepId")
    if step:
        parts.append(f"(step {step})")
    return " ".join(parts)


class JobFailedError(RootCauseError):
    """An asynchronous job finished in a terminal non-success state.

    Attributes:
        job_id (str): The job that failed.
        status (str): The terminal state it ended in.
    """

    def __init__(self, job_id: str, status: str, message: "str | dict | None" = None) -> None:
        self.job_id = job_id
        self.status = status
        self.error = message
        super().__init__(f"Job {job_id} ended as '{status}'" + (f": {_format_job_error(message)}" if message else ""))


class JobTimeoutError(RootCauseError):
    """An asynchronous job did not reach a terminal state within the allotted time.

    The `timeout=` on the call that started it decides how long that is.
    """


class NotFoundInWorkspaceError(RootCauseError):
    """A name or id did not resolve to exactly one object; carries suggestions.

    Attributes:
        kind (str): What was being looked up, for example `workspace` or `twin`.
        needle (str): The name or id that did not resolve.
        candidates (list[str]): The closest names, as suggestions.
    """

    def __init__(self, kind: str, needle: str, candidates: list[str]) -> None:
        self.kind = kind
        self.needle = needle
        self.candidates = candidates
        hint = ""
        if candidates:
            hint = f" Closest matches: {', '.join(candidates[:5])}"
        super().__init__(f'No {kind} named or with id "{needle}".{hint}')


class KindMismatchError(RootCauseError):
    """An explicit twin kind contradicts the panel/temporal kwargs supplied with it."""
