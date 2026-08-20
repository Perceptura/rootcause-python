"""Platform links for SDK objects: every handle knows the page it lives on.

The URL grammar mirrors the platform's own href builders
(`components/Sandbox/sections.ts`) and the MCP deep links — one grammar,
three producers, so a link from `.link()`, a widget's "Open in RootCause"
and the app itself all land on the same page.
"""

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from rootcause._http import Transport


class PlatformLink(str):
    """An absolute platform URL that renders clickable wherever it is shown.

    A plain `str` underneath — pass it anywhere a URL string goes. Its repr is
    the bare URL (most terminals linkify it), and in a notebook it displays as
    an anchor.
    """

    def __repr__(self) -> str:
        return str(self)

    def _repr_html_(self) -> str:
        return f'<a href="{self}" target="_blank" rel="noopener">{self}</a>'


def _organisation_id(transport: "Transport") -> str:
    cached = getattr(transport, "_organisation_id", None)
    if cached:
        return str(cached)
    envelope = transport.request("GET", "/api/v1/me")
    data = envelope.get("data", envelope)
    org_id = str(data.get("organisationId") or "")
    transport._organisation_id = org_id
    return org_id


def workspace_link(transport: "Transport", workspace_id: str, path: str = "") -> PlatformLink:
    org = quote(_organisation_id(transport), safe="")
    return PlatformLink(f"{transport.base_url}/{org}/space/{quote(workspace_id, safe='')}{path}")
