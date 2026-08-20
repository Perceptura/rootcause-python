"""Client-side guards: the mistakes a caller can make, answered with a sentence.

Every check here runs before a request goes out, so a wrong argument costs
nothing and reads as a fix rather than a traceback out of pandas or pyarrow.
"""

import io
from typing import TYPE_CHECKING, Any

from rootcause.errors import (
    InvalidArgumentError,
    MalformedResponseError,
    MissingDependencyError,
)

if TYPE_CHECKING:
    import pandas as pd

_EXTRAS = {"networkx": "graph", "anywidget": "jupyter", "traitlets": "jupyter", "IPython": "jupyter"}


def require(module: str) -> Any:
    """Import an optional dependency, or name the extra that installs it."""
    try:
        return __import__(module)
    except ImportError as error:
        extra = _EXTRAS.get(module)
        install = f'pip install "rootcause-sdk[{extra}]"' if extra else f"pip install {module}"
        raise MissingDependencyError(f"This needs the {module} package: {install}") from error


def frame(value: Any, argument: str = "frame") -> "pd.DataFrame":
    """Accept a non-empty DataFrame, or say what was passed instead."""
    import pandas as pd

    if not isinstance(value, pd.DataFrame):
        if isinstance(value, (list, dict)):
            raise InvalidArgumentError(
                f"{argument}= must be a pandas DataFrame; wrap it first: pd.DataFrame({argument})"
            )
        raise InvalidArgumentError(f"{argument}= must be a pandas DataFrame, not {type(value).__name__}")
    if value.empty:
        raise InvalidArgumentError(f"{argument}= has no rows; there is nothing to model")
    unnamed = [column for column in value.columns if not str(column).strip()]
    if unnamed:
        raise InvalidArgumentError(f"{argument}= has {len(unnamed)} blank column name(s); name every column")
    duplicates = sorted({str(c) for c in value.columns[value.columns.duplicated()]})
    if duplicates:
        raise InvalidArgumentError(f"{argument}= has duplicate column name(s): {', '.join(duplicates)}")
    return value


def positive(value: Any, argument: str) -> int:
    """Accept a positive integer, or say what would have gone to the engine."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise InvalidArgumentError(f"{argument}= must be a whole number, not {value!r}") from None
    if number < 1:
        raise InvalidArgumentError(f"{argument}= must be at least 1, not {number}")
    return number


def probability(value: Any, argument: str) -> float:
    """Accept a probability strictly inside (0, 1)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise InvalidArgumentError(f"{argument}= must be a number between 0 and 1, not {value!r}") from None
    if not 0.0 < number < 1.0:
        raise InvalidArgumentError(f"{argument}= must be between 0 and 1 (exclusive), not {number}")
    return number


def choice(value: Any, argument: str, allowed: "dict[str, Any] | set[str] | list[str]") -> Any:
    """Accept one of a known vocabulary, listing it on a miss."""
    if value in allowed:
        return value
    raise InvalidArgumentError(f'{argument}="{value}" is not one of: {", ".join(sorted(allowed))}')


def to_parquet(value: "pd.DataFrame", argument: str = "frame") -> bytes:
    """Serialise a frame, translating Arrow's complaints about mixed columns."""
    require("pyarrow")
    buffer = io.BytesIO()
    try:
        value.to_parquet(buffer, index=False)
    except Exception as error:
        raise InvalidArgumentError(
            f"{argument}= could not be serialised for upload ({error.__class__.__name__}: {error}). "
            "Columns holding mixed or nested Python objects need converting first."
        ) from error
    return buffer.getvalue()


def from_parquet(blob: bytes, what: str) -> "pd.DataFrame":
    """Read an export back, translating a truncated or non-parquet body."""
    import pandas as pd

    require("pyarrow")
    if not blob:
        raise MalformedResponseError(f"The export of {what} came back empty; it may still be ingesting")
    try:
        return pd.read_parquet(io.BytesIO(blob))
    except Exception as error:
        raise MalformedResponseError(
            f"The export of {what} is not readable parquet ({error.__class__.__name__}: {error})"
        ) from error
