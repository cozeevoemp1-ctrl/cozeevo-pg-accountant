"""
n8nMCP HTTP client — deploys, activates, and manages workflows via n8n REST API.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger


class N8NMCPClient:
    """
    Thin async wrapper around the n8n REST API v1.
    Docs: https://docs.n8n.io/api/api-reference/
    """

    def __init__(self):
        self.base_url = os.getenv("N8N_BASE_URL", "http://localhost:5678").rstrip("/")
        self.api_key  = os.getenv("N8N_API_KEY", "")
        self._headers = {
            "X-N8N-API-KEY": self.api_key,
            "Content-Type":  "application/json",
        }

    @property
    def _api(self) -> str:
        return f"{self.base_url}/api/v1"

    # ── Workflow CRUD ──────────────────────────────────────────────────────

    async def create_workflow(self, workflow: dict) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self._api}/workflows",
                json=workflow,
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"[n8nMCP] Created workflow id={data['id']} name={data['name']}")
            return data

    async def activate_workflow(self, workflow_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(
                f"{self._api}/workflows/{workflow_id}",
                json={"active": True},
                headers=self._headers,
            )
            resp.raise_for_status()
            logger.info(f"[n8nMCP] Activated workflow id={workflow_id}")
            return resp.json()

    async def deactivate_workflow(self, workflow_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(
                f"{self._api}/workflows/{workflow_id}",
                json={"active": False},
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def list_workflows(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self._api}/workflows", headers=self._headers)
            resp.raise_for_status()
            return resp.json().get("data", [])

    async def delete_workflow(self, workflow_id: str):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(
                f"{self._api}/workflows/{workflow_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            logger.info(f"[n8nMCP] Deleted workflow id={workflow_id}")

    # ── Deploy from JSON file ──────────────────────────────────────────────

    async def deploy_from_file(self, json_path: str | Path, activate: bool = True) -> dict:
        import json
        path = Path(json_path)
        workflow = json.loads(path.read_text(encoding="utf-8"))
        data = await self.create_workflow(workflow)
        if activate:
            await self.activate_workflow(data["id"])
        return data

    async def deploy_all(self, workflows_dir: str | Path = "./workflows/n8n") -> list[dict]:
        """Deploy all JSON files in the workflows directory."""
        wdir = Path(workflows_dir)
        deployed = []
        for f in wdir.glob("*.json"):
            try:
                result = await self.deploy_from_file(f)
                deployed.append(result)
            except Exception as e:
                logger.error(f"[n8nMCP] Failed to deploy {f.name}: {e}")
        logger.info(f"[n8nMCP] Deployed {len(deployed)} workflows.")
        return deployed

    async def ping(self) -> bool:
        """Check if n8n is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/healthz")
                return resp.status_code == 200
        except Exception:
            return False
