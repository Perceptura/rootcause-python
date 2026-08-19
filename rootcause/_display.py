"""Result objects mount their interactive app when a notebook displays them.

The hook is `_ipython_display_`, which only fires when an object is actually
shown — the last expression of a cell, or an explicit `display()`. Assigning a
result to a variable renders nothing, and scripts outside a kernel never enter
this path, so the verbs stay verbs: no call ever computes for the sake of a
picture, apps only mount over results that already exist (or free reads like
the causal graph).
"""

import os
from typing import Any, Callable

_state: dict[str, "bool | None"] = {"enabled": None}


def auto_apps(enabled: "bool | None" = None) -> bool:
    """Whether displayed result objects mount their interactive app.

    On by default. Off, every object falls back to its static HTML repr — the
    right setting for headless notebook executors and exported documents.
    `ROOTCAUSE_AUTO_APPS=0` sets the same switch from the environment.

    Args:
        enabled: Pass True/False to change the setting; omit to just read it.

    Returns:
        The setting now in effect.
    """
    if enabled is not None:
        _state["enabled"] = bool(enabled)
    current = _state["enabled"]
    if current is None:
        return os.environ.get("ROOTCAUSE_AUTO_APPS", "1").strip().lower() not in ("0", "false", "no")
    return current


def show(obj: Any, mount: Callable[[], Any]) -> None:
    """The `_ipython_display_` contract: try the app, never raise, degrade to the static repr."""
    from IPython.display import HTML, display

    if auto_apps():
        try:
            display(mount())
            return
        except Exception:
            pass
    html = getattr(obj, "_repr_html_", None)
    display(HTML(html()) if callable(html) else repr(obj))
