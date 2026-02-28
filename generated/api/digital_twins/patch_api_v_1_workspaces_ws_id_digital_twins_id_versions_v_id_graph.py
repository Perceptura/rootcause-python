from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.patch_api_v1_workspaces_ws_id_digital_twins_id_versions_v_id_graph_response_200 import PatchApiV1WorkspacesWsIdDigitalTwinsIdVersionsVIdGraphResponse200
from ...models.problem_detail import ProblemDetail
from typing import cast



def _get_kwargs(
    ws_id: str,
    id: str,
    v_id: str,

) -> dict[str, Any]:
    

    

    

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/api/v1/workspaces/{ws_id}/digital-twins/{id}/versions/{v_id}/graph".format(ws_id=quote(str(ws_id), safe=""),id=quote(str(id), safe=""),v_id=quote(str(v_id), safe=""),),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> PatchApiV1WorkspacesWsIdDigitalTwinsIdVersionsVIdGraphResponse200 | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = PatchApiV1WorkspacesWsIdDigitalTwinsIdVersionsVIdGraphResponse200.from_dict(response.json())



        return response_200

    if response.status_code == 401:
        response_401 = ProblemDetail.from_dict(response.json())



        return response_401

    if response.status_code == 403:
        response_403 = ProblemDetail.from_dict(response.json())



        return response_403

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[PatchApiV1WorkspacesWsIdDigitalTwinsIdVersionsVIdGraphResponse200 | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    ws_id: str,
    id: str,
    v_id: str,
    *,
    client: AuthenticatedClient,

) -> Response[PatchApiV1WorkspacesWsIdDigitalTwinsIdVersionsVIdGraphResponse200 | ProblemDetail]:
    """ Patch causal graph

    Args:
        ws_id (str):
        id (str):
        v_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PatchApiV1WorkspacesWsIdDigitalTwinsIdVersionsVIdGraphResponse200 | ProblemDetail]
     """


    kwargs = _get_kwargs(
        ws_id=ws_id,
id=id,
v_id=v_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    ws_id: str,
    id: str,
    v_id: str,
    *,
    client: AuthenticatedClient,

) -> PatchApiV1WorkspacesWsIdDigitalTwinsIdVersionsVIdGraphResponse200 | ProblemDetail | None:
    """ Patch causal graph

    Args:
        ws_id (str):
        id (str):
        v_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PatchApiV1WorkspacesWsIdDigitalTwinsIdVersionsVIdGraphResponse200 | ProblemDetail
     """


    return sync_detailed(
        ws_id=ws_id,
id=id,
v_id=v_id,
client=client,

    ).parsed

async def asyncio_detailed(
    ws_id: str,
    id: str,
    v_id: str,
    *,
    client: AuthenticatedClient,

) -> Response[PatchApiV1WorkspacesWsIdDigitalTwinsIdVersionsVIdGraphResponse200 | ProblemDetail]:
    """ Patch causal graph

    Args:
        ws_id (str):
        id (str):
        v_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PatchApiV1WorkspacesWsIdDigitalTwinsIdVersionsVIdGraphResponse200 | ProblemDetail]
     """


    kwargs = _get_kwargs(
        ws_id=ws_id,
id=id,
v_id=v_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    ws_id: str,
    id: str,
    v_id: str,
    *,
    client: AuthenticatedClient,

) -> PatchApiV1WorkspacesWsIdDigitalTwinsIdVersionsVIdGraphResponse200 | ProblemDetail | None:
    """ Patch causal graph

    Args:
        ws_id (str):
        id (str):
        v_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PatchApiV1WorkspacesWsIdDigitalTwinsIdVersionsVIdGraphResponse200 | ProblemDetail
     """


    return (await asyncio_detailed(
        ws_id=ws_id,
id=id,
v_id=v_id,
client=client,

    )).parsed
