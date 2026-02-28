from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_api_v1_connectors_id_browse_response_200 import GetApiV1ConnectorsIdBrowseResponse200
from ...models.problem_detail import ProblemDetail
from typing import cast



def _get_kwargs(
    id: str,

) -> dict[str, Any]:
    

    

    

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/connectors/{id}/browse".format(id=quote(str(id), safe=""),),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> GetApiV1ConnectorsIdBrowseResponse200 | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = GetApiV1ConnectorsIdBrowseResponse200.from_dict(response.json())



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


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[GetApiV1ConnectorsIdBrowseResponse200 | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    id: str,
    *,
    client: AuthenticatedClient,

) -> Response[GetApiV1ConnectorsIdBrowseResponse200 | ProblemDetail]:
    """ Browse connector resources

    Args:
        id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GetApiV1ConnectorsIdBrowseResponse200 | ProblemDetail]
     """


    kwargs = _get_kwargs(
        id=id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    id: str,
    *,
    client: AuthenticatedClient,

) -> GetApiV1ConnectorsIdBrowseResponse200 | ProblemDetail | None:
    """ Browse connector resources

    Args:
        id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GetApiV1ConnectorsIdBrowseResponse200 | ProblemDetail
     """


    return sync_detailed(
        id=id,
client=client,

    ).parsed

async def asyncio_detailed(
    id: str,
    *,
    client: AuthenticatedClient,

) -> Response[GetApiV1ConnectorsIdBrowseResponse200 | ProblemDetail]:
    """ Browse connector resources

    Args:
        id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GetApiV1ConnectorsIdBrowseResponse200 | ProblemDetail]
     """


    kwargs = _get_kwargs(
        id=id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    id: str,
    *,
    client: AuthenticatedClient,

) -> GetApiV1ConnectorsIdBrowseResponse200 | ProblemDetail | None:
    """ Browse connector resources

    Args:
        id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GetApiV1ConnectorsIdBrowseResponse200 | ProblemDetail
     """


    return (await asyncio_detailed(
        id=id,
client=client,

    )).parsed
