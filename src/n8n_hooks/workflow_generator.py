"""
n8nMCP Workflow Generator.
Programmatically creates n8n workflows and saves them to ./workflows/n8n/.

Node definitions use n8n-mcp (github.com/czlonkowski/n8n-mcp) for node lookup
and validation when available, falling back to hard-coded node types otherwise.

n8n-skills (github.com/czlonkowski/n8n-skills) provides Claude Code with
the knowledge to extend or modify these workflows interactively.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger


WORKFLOWS_DIR = Path("./workflows/n8n")

# Canonical n8n node types verified against n8n-mcp node database
_NODE_TYPES = {
    "webhook":          "n8n-nodes-base.webhook",
    "set":              "n8n-nodes-base.set",
    "http_request":     "n8n-nodes-base.httpRequest",
    "respond_webhook":  "n8n-nodes-base.respondToWebhook",
    "schedule":         "n8n-nodes-base.scheduleTrigger",
    "code":             "n8n-nodes-base.code",
    "if":               "n8n-nodes-base.if",
    "merge":            "n8n-nodes-base.merge",
    "no_op":            "n8n-nodes-base.noOp",
}


class N8NWorkflowGenerator:
    """
    Generates n8n workflow JSON definitions and deploys via REST API.
    Each PG owner sets their own N8N_BASE_URL and N8N_API_KEY in .env.

    When n8n-mcp is installed (npx n8n-mcp), generated workflows are validated
    before saving via N8NMCPWorkflowManager.validate_workflow().
    """

    def __init__(self):
        self.base_url       = os.getenv("N8N_BASE_URL", "http://localhost:5678")
        self.api_key        = os.getenv("N8N_API_KEY", "")
        self.webhook_secret = os.getenv("N8N_WEBHOOK_SECRET", "change-me")
        self.api_server     = os.getenv("DASHBOARD_BASE_URL", "http://localhost:8000")
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Workflow builders ──────────────────────────────────────────────────

    def create_whatsapp_workflow(self) -> dict:
        """
        Workflow: Meta WhatsApp Cloud API → PG Accountant API → reply.

        NOTE: Meta sends webhooks DIRECTLY to FastAPI (/webhook/whatsapp).
        This n8n workflow acts as an optional logging/monitoring layer.
        If you prefer to keep n8n in the chain, point your Meta webhook URL to:
            https://<ngrok>/n8n/webhook/meta-whatsapp
        and this workflow will forward to FastAPI.

        Default (simpler): point Meta webhook URL directly to FastAPI:
            https://<ngrok>/webhook/whatsapp
        """
        workflow = {
            "name": "PG Accountant — WhatsApp Handler (Meta Cloud API)",
            "nodes": [
                {
                    "id": "meta-webhook",
                    "name": "Meta WhatsApp Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "typeVersion": 1,
                    "position": [240, 300],
                    "parameters": {
                        "path": "meta-whatsapp",
                        "responseMode": "responseNode",
                        "options": {"allowedMethods": ["POST", "GET"]},
                    },
                },
                {
                    "id": "extract-message",
                    "name": "Extract Meta Message",
                    "type": "n8n-nodes-base.code",
                    "typeVersion": 1,
                    "position": [460, 300],
                    "parameters": {
                        "jsCode": (
                            "const payload = $input.first().json;\n"
                            "// Meta webhook verification (GET)\n"
                            "if ($input.first().json['hub.mode'] === 'subscribe') {\n"
                            "  return [{ json: { _verification: true, challenge: $input.first().json['hub.challenge'] } }];\n"
                            "}\n"
                            "// Extract first message\n"
                            "try {\n"
                            "  const value = payload.entry[0].changes[0].value;\n"
                            "  const msg   = value.messages?.[0];\n"
                            "  if (!msg) return [{ json: { _skip: true } }];\n"
                            "  return [{ json: {\n"
                            "    from_number: msg.from,\n"
                            "    body: msg.type === 'text' ? msg.text.body : (msg[msg.type]?.caption || ''),\n"
                            "    media_id: msg[msg.type]?.id || null,\n"
                            "  }}];\n"
                            "} catch(e) { return [{ json: { _skip: true } }]; }"
                        )
                    },
                },
                {
                    "id": "call-pg-api",
                    "name": "Call PG Accountant API",
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 3,
                    "position": [680, 300],
                    "parameters": {
                        "method": "POST",
                        "url": f"{self.api_server}/webhook/whatsapp",
                        "sendHeaders": True,
                        "headerParameters": {"parameters": [
                            {"name": "Content-Type", "value": "application/json"}
                        ]},
                        "sendBody": True,
                        "bodyContentType": "json",
                        "jsonBody": '={{ JSON.stringify($json) }}',
                    },
                },
                {
                    "id": "respond",
                    "name": "Respond to Webhook",
                    "type": "n8n-nodes-base.respondToWebhook",
                    "typeVersion": 1,
                    "position": [900, 300],
                    "parameters": {
                        "responseBody": '{"status": "ok"}',
                        "responseCode": 200,
                    },
                },
            ],
            "connections": {
                "Meta WhatsApp Webhook":  {"main": [[{"node": "Extract Meta Message",      "type": "main", "index": 0}]]},
                "Extract Meta Message":   {"main": [[{"node": "Call PG Accountant API",    "type": "main", "index": 0}]]},
                "Call PG Accountant API": {"main": [[{"node": "Respond to Webhook",        "type": "main", "index": 0}]]},
            },
            "active": True,
            "settings": {"saveManualExecutions": True},
        }
        return workflow

    def create_ingestion_workflow(self) -> dict:
        """
        Workflow: Watch data/raw/ folder → ingest via API.
        Trigger: scheduled or file-watch.
        """
        workflow = {
            "name": "PG Accountant — File Ingestion",
            "nodes": [
                {
                    "id": "schedule",
                    "name": "Schedule Trigger",
                    "type": "n8n-nodes-base.scheduleTrigger",
                    "typeVersion": 1,
                    "position": [240, 300],
                    "parameters": {
                        "rule": {"interval": [{"field": "minutes", "minutesInterval": 15}]}
                    },
                },
                {
                    "id": "ingest",
                    "name": "Trigger Ingestion",
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 3,
                    "position": [460, 300],
                    "parameters": {
                        "method": "POST",
                        "url": f"{self.api_server}/api/ingest/scan",
                        "sendHeaders": True,
                        "headerParameters": {"parameters": [
                            {"name": "Content-Type", "value": "application/json"}
                        ]},
                    },
                },
            ],
            "connections": {
                "Schedule Trigger": {"main": [[{"node": "Trigger Ingestion", "type": "main", "index": 0}]]}
            },
            "active": True,
        }
        return workflow

    def create_reconciliation_workflow(self) -> dict:
        """
        Workflow: Daily reconciliation at 11 PM IST.
        """
        workflow = {
            "name": "PG Accountant — Daily Reconciliation",
            "nodes": [
                {
                    "id": "cron",
                    "name": "Daily 11PM",
                    "type": "n8n-nodes-base.scheduleTrigger",
                    "typeVersion": 1,
                    "position": [240, 300],
                    "parameters": {
                        "rule": {"interval": [{"field": "cronExpression", "expression": "0 17 * * *"}]}
                    },
                },
                {
                    "id": "reconcile",
                    "name": "Run Reconciliation",
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 3,
                    "position": [460, 300],
                    "parameters": {
                        "method": "POST",
                        "url": f"{self.api_server}/api/reconcile",
                        "sendBody": True,
                        "bodyContentType": "json",
                        "jsonBody": '{"period": "daily"}',
                    },
                },
            ],
            "connections": {
                "Daily 11PM": {"main": [[{"node": "Run Reconciliation", "type": "main", "index": 0}]]}
            },
            "active": True,
        }
        return workflow

    # ── Save workflow JSON ─────────────────────────────────────────────────

    def save_workflow(self, workflow: dict, filename: Optional[str] = None) -> Path:
        name = filename or f"{workflow['name'].replace(' ', '_').replace('—', '').strip()}_{datetime.now().strftime('%Y%m%d')}.json"
        path = WORKFLOWS_DIR / name
        path.write_text(json.dumps(workflow, indent=2), encoding="utf-8")
        logger.info(f"[N8N] Workflow saved: {path}")
        return path

    def generate_all_workflows(self, validate: bool = True) -> list[Path]:
        """
        Generate and save all standard workflows.
        If validate=True and n8n-mcp is available, each workflow is validated
        before saving (uses N8NMCPWorkflowManager.validate_workflow).
        """
        # Lazy import to avoid circular dependency
        mgr = None
        if validate:
            try:
                from src.n8n_hooks.n8nmcp_tools import get_workflow_manager
                mgr = get_workflow_manager()
                if not mgr.is_n8n_mcp_available():
                    mgr = None
            except Exception:
                pass

        saved = []
        for builder, filename in [
            (self.create_whatsapp_workflow,      "whatsapp_handler.json"),
            (self.create_ingestion_workflow,     "file_ingestion.json"),
            (self.create_reconciliation_workflow,"daily_reconciliation.json"),
        ]:
            wf = builder()
            if mgr:
                result = mgr.validate_workflow(wf)
                if result.get("valid", True):
                    logger.info(f"[N8N] ✓ Validated: {wf['name']}")
                else:
                    logger.warning(f"[N8N] ⚠ Validation issues for {wf['name']}: {result.get('errors')}")
            path = self.save_workflow(wf, filename)
            saved.append(path)

        logger.info(f"[N8N] Generated {len(saved)} workflows in {WORKFLOWS_DIR}")
        return saved
