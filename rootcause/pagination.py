from typing import Any, AsyncGenerator, Callable, Awaitable


async def paginate(
    fetch_page: Callable[[str | None], Awaitable[dict[str, Any]]],
) -> AsyncGenerator[Any, None]:
    """Auto-paginate through a cursor-based endpoint."""
    cursor: str | None = None

    while True:
        page = await fetch_page(cursor)
        data = page.get("data", [])

        for item in data:
            yield item

        pagination = page.get("pagination", {})
        if not pagination.get("hasMore") or not pagination.get("cursor"):
            break

        cursor = pagination["cursor"]
