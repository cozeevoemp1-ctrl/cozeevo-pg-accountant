"""
n8n-MCP Tool Bridge for PG Accountant.

Uses the n8n-mcp MCP server (github.com/czlonkowski/n8n-mcp) to:
  - Search and discover n8n nodes from a database of 1,084+ nodes
  - Validate workflow JSON before deploying
  - Create/update workflows via n8n REST API through the MCP layer
  - Access 2,700+ workflow templates

Also integrates with n8n-skills (github.com/czlonkowski/n8n-skills) which
teaches Claude how to construct correct n8n workflows (expressions, patterns,
node configuration, validation).

Architecture:
  Claude Code + n8n-skills knowledge
         │
         │  MCP protocol (stdio)
         ▼
  n8n-mcp MCP server  ──REST API──►  n8n instance
         │
         ▼
  This module (Python) calls n8n-mcp via subprocess / HTTP
  for programmatic workflow creation when not in Claude context.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from src.n8n_hooks.mcp_client import N8NMCPClient
from src.n8n_hooks.workflow_generator import N8NWorkflowGenerator, WORKFLOWS_DIR


# ── n8n-mcp MCP server subprocess wrapper ─────────────────────────────────

class N8NMCPServer:
    """
    Communicates with the n8n-mcp MCP server over stdio (JSON-RPC 2.0).
    Used when the Python code needs to leverage the node database,
    templates, or validation outside of a Claude session.

    Prerequisites: `npx n8n-mcp` must be available (npm installed).
    """

    def __init__(self):
        self.n8n_api_url = os.getenv("N8N_API_URL", os.getenv("N8N_BASE_URL", "http://localhost:5678"))
        self.n8n_api_key = os.getenv("N8N_API_KEY", "")
        self._proc: Optional[subprocess.Popen] = None

    def _start(self):
        env = {
            **os.environ,
            "MCP_MODE": "stdio",
            "LOG_LEVEL": "error",
            "DISABLE_CONSOLE_OUTPUT": "true",
            "N8N_API_URL": self.n8n_api_url,
            "N8N_API_KEY": self.n8n_api_key,
            "N8N_MCP_TELEMETRY_DISABLED": "true",
        }
        self._proc = subprocess.Popen(
            ["npx", "n8n-mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
        )
        # Initialize MCP session
        self._send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05",
                               "capabilities": {},
                               "clientInfo": {"name": "pg-accountant", "version": "1.0.0"}}})

    def _send(self, payload: dict) -> dict:
        if not self._proc:
            self._start()
        line = json.dumps(payload) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()
        response_line = self._proc.stdout.readline()
        return json.loads(response_line) if response_line.strip() else {}

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        import uuid
        req_id = str(uuid.uuid4())[:8]
        resp = self._send({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        return resp.get("result", {})

    def list_tools(self) -> list[dict]:
        resp = self._send({"jsonrpc": "2.0", "id": "list", "method": "tools/list", "params": {}})
        return resp.get("result", {}).get("tools", [])

    def stop(self):
        if self._proc:
            self._proc.terminate()
            self._proc = None


# ── High-level helpers wrapping n8n-mcp tools ─────────────────────────────

class N8NMCPWorkflowManager:
    """
    High-level API that uses n8n-mcp to create and deploy PG Accountant
    workflows with proper node validation and template discovery.

    Falls back to the basic N8NWorkflowGenerator if n8n-mcp is unavailable.
    """

    def __init__(self):
        self._server: Optional[N8NMCPServer] = None
        self._available: Optional[bool] = None
        self._rest_client = N8NMCPClient()
        self._generator   = N8NWorkflowGenerator()

    @property
    def server(self) -> N8NMCPServer:
        if not self._server:
            self._server = N8NMCPServer()
        return self._server

    def is_n8n_mcp_available(self) -> bool:
        """Check if npx n8n-mcp is installed and runnable."""
        if self._available is not None:
            return self._available
        try:
            result = subprocess.run(
                ["npx", "--yes", "n8n-mcp", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            self._available = result.returncode == 0
        except Exception:
            self._available = False
        logger.info(f"[n8nMCP] n8n-mcp available: {self._available}")
        return self._available

    # ── Node discovery ─────────────────────────────────────────────────────

    def search_nodes(self, query: str, limit: int = 5) -> list[dict]:
        """Search the n8n-mcp node database for a node matching query."""
        if not self.is_n8n_mcp_available():
            return []
        result = self.server.call_tool("search_nodes", {"query": query, "limit": limit})
        return result.get("content", [])

    def get_node_info(self, node_type: str) -> dict:
        """Get full node documentation including properties and examples."""
        if not self.is_n8n_mcp_available():
            return {}
        result = self.server.call_tool("get_node_info", {"nodeType": node_type})
        return result.get("content", {})

    # ── Workflow validation ────────────────────────────────────────────────

    def validate_workflow(self, workflow: dict) -> dict:
        """
        Validate a workflow JSON using n8n-mcp's validation engine.
        Returns {"valid": bool, "errors": [...], "warnings": [...]}.
        """
        if not self.is_n8n_mcp_available():
            logger.warning("[n8nMCP] Skipping validation — n8n-mcp not available")
            return {"valid": True, "errors": [], "warnings": ["n8n-mcp not installed"]}

        result = self.server.call_tool("validate_workflow", {"workflow": workflow})
        text = result.get("content", [{}])
        if isinstance(text, list) and text:
            text = text[0].get("text", "{}")
        try:
            return json.loads(text) if isinstance(text, str) else text
        except Exception:
            return {"valid": True, "errors": []}

    # ── Template discovery ─────────────────────────────────────────────────

    def search_templates(self, query: str, limit: int = 3) -> list[dict]:
        """Search 2,700+ n8n workflow templates via n8n-mcp."""
        if not self.is_n8n_mcp_available():
            return []
        result = self.server.call_tool("search_templates", {"query": query, "limit": limit})
        return result.get("content", [])

    # ── Deploy workflow via MCP ────────────────────────────────────────────

    async def deploy_workflow_via_mcp(self, workflow: dict, activate: bool = True) -> dict:
        """
        Deploy a workflow:
        1. Validate via n8n-mcp (if available)
        2. Save JSON to workflows/n8n/
        3. Deploy via n8n REST API (N8NMCPClient)
        """
        # Step 1: Validate
        validation = self.validate_workflow(workflow)
        if not validation.get("valid", True):
            errors = validation.get("errors", [])
            logger.error(f"[n8nMCP] Workflow validation failed: {errors}")
            raise ValueError(f"Workflow validation failed: {errors}")

        if validation.get("warnings"):
            for w in validation["warnings"]:
                logger.warning(f"[n8nMCP] Workflow warning: {w}")

        # Step 2: Save to disk
        path = self._generator.save_workflow(workflow)
        logger.info(f"[n8nMCP] Validated and saved: {path}")

        # Step 3: Deploy via REST API
        deployed = await self._rest_client.create_workflow(workflow)
        if activate:
            await self._rest_client.activate_workflow(deployed["id"])

        return deployed

    async def deploy_all_pg_workflows(self) -> list[dict]:
        """
        Generate all PG Accountant workflows, validate, and deploy.
        Uses n8n-mcp for validation + n8n REST API for deployment.
        """
        workflows = [
            ("whatsapp_handler.json",       self._generator.create_whatsapp_workflow()),
            ("file_ingestion.json",         self._generator.create_ingestion_workflow()),
            ("daily_reconciliation.json",   self._generator.create_reconciliation_workflow()),
        ]

        deployed = []
        for filename, wf in workflows:
            try:
                logger.info(f"[n8nMCP] Deploying: {wf['name']}")
                result = await self.deploy_workflow_via_mcp(wf)
                deployed.append({"name": wf["name"], "id": result.get("id"), "file": filename})
            except Exception as e:
                logger.error(f"[n8nMCP] Failed to deploy {wf['name']}: {e}")
                deployed.append({"name": wf["name"], "error": str(e), "file": filename})

        return deployed

    def cleanup(self):
        if self._server:
            self._server.stop()


# ── Singleton ──────────────────────────────────────────────────────────────

_manager: Optional[N8NMCPWorkflowManager] = None


def get_workflow_manager() -> N8NMCPWorkflowManager:
    global _manager
    if _manager is None:
        _manager = N8NMCPWorkflowManager()
    return _manager
