from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.post_api_v1_workspaces_ws_id_reports_response_201 import PostApiV1WorkspacesWsIdReportsResponse201
from ...models.problem_detail import ProblemDetail
from typing import cast



def _get_kwargs(
    ws_id: str,

) -> dict[str, Any]:
    

    

    

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/workspaces/{ws_id}/reports".format(ws_id=quote(str(ws_id), safe=""),),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> PostApiV1WorkspacesWsIdReportsResponse201 | ProblemDetail | None:
    if response.status_code == 201:
        response_201 = PostApiV1WorkspacesWsIdReportsResponse201.from_dict(response.json())



        return response_201

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


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[PostApiV1WorkspacesWsIdReportsResponse201 | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    ws_id: str,
    *,
    client: AuthenticatedClient,

) -> Response[PostApiV1WorkspacesWsIdReportsResponse201 | ProblemDetail]:
    """ Create report

    Args:
        ws_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiV1WorkspacesWsIdReportsResponse201 | ProblemDetail]
     """


    kwargs = _get_kwargs(
        ws_id=ws_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    ws_id: str,
    *,
    client: AuthenticatedClient,

) -> PostApiV1WorkspacesWsIdReportsResponse201 | ProblemDetail | None:
    """ Create report

    Args:
        ws_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiV1WorkspacesWsIdReportsResponse201 | ProblemDetail
     """


    return sync_detailed(
        ws_id=ws_id,
client=client,

    ).parsed

async def asyncio_detailed(
    ws_id: str,
    *,
    client: AuthenticatedClient,

) -> Response[PostApiV1WorkspacesWsIdReportsResponse201 | ProblemDetail]:
    """ Create report

    Args:
        ws_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiV1WorkspacesWsIdReportsResponse201 | ProblemDetail]
     """


    kwargs = _get_kwargs(
        ws_id=ws_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    ws_id: str,
    *,
    client: AuthenticatedClient,

) -> PostApiV1WorkspacesWsIdReportsResponse201 | ProblemDetail | None:
    """ Create report

    Args:
        ws_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiV1WorkspacesWsIdReportsResponse201 | ProblemDetail
     """


    return (await asyncio_detailed(
        ws_id=ws_id,
client=client,

    )).parsed
