import asyncio
from typing import Any, Callable, Awaitable

from rootcause.errors import RootCauseTimeoutError


async def poll_job(
    fetch_job: Callable[[], Awaitable[dict[str, Any]]],
    interval_seconds: float = 2.0,
    timeout_seconds: float = 300.0,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Poll a job until it reaches a terminal state."""
    elapsed = 0.0
    job_id = ""

    while elapsed < timeout_seconds:
        job = await fetch_job()
        job_id = job.get("id", job_id)

        if on_progress:
            on_progress(job)

        status = job.get("status", "")
        if status in ("completed", "failed", "cancelled"):
            return job

        await asyncio.sleep(interval_seconds)
        elapsed += interval_seconds

    raise RootCauseTimeoutError(job_id, timeout_seconds)
