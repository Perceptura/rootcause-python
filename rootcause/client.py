from typing import Any

import httpx

from rootcause.errors import RootCauseApiError


class RootCauseConfig:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://platform.rootcause.ai",
        workspace_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.workspace_id = workspace_id
        self.timeout = timeout


class RootCause:
    def __init__(self, config: RootCauseConfig | None = None, **kwargs: Any) -> None:
        if config is None:
            config = RootCauseConfig(**kwargs)
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=config.timeout,
        )
        self.workspaces = WorkspacesNamespace(self)
        self.datasets = DatasetsNamespace(self)
        self.data_views = DataViewsNamespace(self)
        self.ontology = OntologyNamespace(self)
        self.digital_twins = DigitalTwinsNamespace(self)
        self.jobs = JobsNamespace(self)
        self.simulations = SimulationsNamespace(self)
        self.reports = ReportsNamespace(self)
        self.agent = AgentNamespace(self)

    @property
    def workspace_id(self) -> str | None:
        return self._config.workspace_id

    @workspace_id.setter
    def workspace_id(self, value: str | None) -> None:
        self._config.workspace_id = value

    def _ws(self, override: str | None = None) -> str:
        ws_id = override or self._config.workspace_id
        if not ws_id:
            raise ValueError("workspace_id is required. Set it on the client or pass it explicitly.")
        return ws_id

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = {"detail": response.text}
            raise RootCauseApiError.from_response(body, response.status_code)
        if response.status_code == 204:
            return {}
        return response.json()

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "RootCause":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


class _Namespace:
    def __init__(self, client: RootCause) -> None:
        self._rc = client


class WorkspacesNamespace(_Namespace):
    async def list(self) -> dict[str, Any]:
        return await self._rc._request("GET", "/api/v1/workspaces")

    async def get(self, workspace_id: str) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{workspace_id}")

    async def create(self, name: str, description: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name}
        if description:
            body["description"] = description
        return await self._rc._request("POST", "/api/v1/workspaces", json=body)

    async def update(self, workspace_id: str, **kwargs: Any) -> dict[str, Any]:
        return await self._rc._request("PATCH", f"/api/v1/workspaces/{workspace_id}", json=kwargs)

    async def delete(self, workspace_id: str) -> dict[str, Any]:
        return await self._rc._request("DELETE", f"/api/v1/workspaces/{workspace_id}")


class DatasetsNamespace(_Namespace):
    async def list(self, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/datasets")

    async def get(self, dataset_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/datasets/{dataset_id}")

    async def create(self, body: dict[str, Any], workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("POST", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/datasets", json=body)

    async def update(self, dataset_id: str, body: dict[str, Any], workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("PATCH", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/datasets/{dataset_id}", json=body)

    async def delete(self, dataset_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("DELETE", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/datasets/{dataset_id}")

    async def schema(self, dataset_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/datasets/{dataset_id}/schema")

    async def records(self, dataset_id: str, workspace_id: str | None = None, **params: Any) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/datasets/{dataset_id}/records", params=params)


class DataViewsNamespace(_Namespace):
    async def list(self, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/data-views")

    async def get(self, view_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/data-views/{view_id}")

    async def create(self, body: dict[str, Any], workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("POST", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/data-views", json=body)

    async def update(self, view_id: str, body: dict[str, Any], workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("PATCH", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/data-views/{view_id}", json=body)

    async def delete(self, view_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("DELETE", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/data-views/{view_id}")


class OntologyNamespace(_Namespace):
    async def concepts(self, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/ontology/concepts")

    async def graph(self, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/ontology/graph")


class DigitalTwinsNamespace(_Namespace):
    async def list(self, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/digital-twins")

    async def get(self, twin_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/digital-twins/{twin_id}")

    async def create(self, body: dict[str, Any], workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("POST", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/digital-twins", json=body)


class JobsNamespace(_Namespace):
    async def list(self, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/jobs")

    async def get(self, job_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/jobs/{job_id}")

    async def cancel(self, job_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("POST", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/jobs/{job_id}/cancel")


class SimulationsNamespace(_Namespace):
    async def run(self, body: dict[str, Any], workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("POST", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/simulations", json=body)

    async def get(self, sim_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/simulations/{sim_id}")

    async def results(self, sim_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/simulations/{sim_id}/results")


class ReportsNamespace(_Namespace):
    async def list(self, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/reports")

    async def get(self, report_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/reports/{report_id}")

    async def create(self, body: dict[str, Any], workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("POST", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/reports", json=body)

    async def generate(self, report_id: str, body: dict[str, Any], workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("POST", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/reports/{report_id}/generate", json=body)


class AgentNamespace(_Namespace):
    async def chat(self, body: dict[str, Any], workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("POST", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/agent/chat", json=body)

    async def tools(self, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/agent/tools")

    async def sessions(self, workspace_id: str | None = None) -> dict[str, Any]:
        return await self._rc._request("GET", f"/api/v1/workspaces/{self._rc._ws(workspace_id)}/agent/sessions")
