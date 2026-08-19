"""Exception hierarchy for the SDK; every error derives from RootCauseError."""

from typing import Any


class RootCauseError(Exception):
    """Base class for every error this SDK raises."""


class AuthenticationError(RootCauseError):
    """No usable credentials, or the platform rejected the ones provided."""


class RootCauseApiError(RootCauseError):
    """The API answered with a problem response.

    Attributes:
        status (int): HTTP status code.
        title (str): Short problem title from the API.
        detail (str): The API's explanation.
        body (Any): The raw problem body, when it was JSON.
    """

    def __init__(self, status: int, title: str, detail: str, body: Any = None) -> None:
        self.status = status
        self.title = title
        self.detail = detail
        self.body = body
        super().__init__(f"[{status} {title}] {detail}")

    @classmethod
    def from_response(cls, body: Any, status: int) -> "RootCauseApiError":
        if isinstance(body, dict):
            title = str(body.get("title") or body.get("error") or "Error")
            detail = str(body.get("detail") or body.get("error") or body)
            return cls(status, title, detail, body)
        return cls(status, "Error", str(body), body)


class JobFailedError(RootCauseError):
    """An asynchronous job finished in a terminal non-success state.

    Attributes:
        job_id (str): The job that failed.
        status (str): The terminal state it ended in.
    """

    def __init__(self, job_id: str, status: str, message: str | None = None) -> None:
        self.job_id = job_id
        self.status = status
        super().__init__(f"Job {job_id} ended as '{status}'" + (f": {message}" if message else ""))


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
