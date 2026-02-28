from typing import Any


class RootCauseError(Exception):
    pass


class RootCauseApiError(RootCauseError):
    def __init__(self, status: int, type_url: str, title: str, detail: str, instance: str | None = None) -> None:
        super().__init__(f"{title}: {detail}")
        self.status = status
        self.type_url = type_url
        self.title = title
        self.detail = detail
        self.instance = instance

    @classmethod
    def from_response(cls, response_data: dict[str, Any], status_code: int) -> "RootCauseApiError":
        return cls(
            status=status_code,
            type_url=response_data.get("type", ""),
            title=response_data.get("title", "Unknown Error"),
            detail=response_data.get("detail", "No details provided"),
            instance=response_data.get("instance"),
        )


class RootCauseTimeoutError(RootCauseError):
    def __init__(self, job_id: str, timeout_seconds: float) -> None:
        super().__init__(f"Job {job_id} did not complete within {timeout_seconds}s")
        self.job_id = job_id
        self.timeout_seconds = timeout_seconds
