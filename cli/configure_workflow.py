"""
CLI: configure-workflow
Interactive VS Code terminal wizard — covers full n8n-mcp + n8n-skills + deployment.

Steps:
  1. Prerequisites (Node.js, npx, n8n-mcp, n8n-skills)
  2. n8n connection verification
  3. .mcp.json for Claude Code MCP server
  4. n8n-skills Claude Code plugin
  5. Twilio WhatsApp
  6. Anthropic API key
  7. Workflow generation + n8n-mcp validation
  8. Deploy to n8n

Repos used:
  https://github.com/czlonkowski/n8n-mcp
  https://github.com/czlonkowski/n8n-skills
"""
import asyncio
import json
import os
import platform
import secrets
import shutil
import subprocess
from pathlib import Path

import click
import questionary
from dotenv import load_dotenv, set_key
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

load_dotenv()
console = Console()
ENV_FILE = Path(".env")


# ── Helpers ────────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 15) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout.strip() or r.stderr.strip())[:120]
    except Exception as e:
        return False, str(e)[:80]


def _save_env(key: str, value: str):
    """Upsert a key into .env (creates file if absent)."""
    if not ENV_FILE.exists():
        ENV_FILE.write_text("")
    set_key(str(ENV_FILE), key, value)
    os.environ[key] = value   # also update current process


def _write_mcp_json(n8n_url: str, n8n_key: str):
    config = {
        "mcpServers": {
            "n8n-mcp": {
                "command": "npx",
                "args": ["n8n-mcp"],
                "env": {
                    "MCP_MODE": "stdio",
                    "LOG_LEVEL": "error",
                    "DISABLE_CONSOLE_OUTPUT": "true",
                    "N8N_API_URL": n8n_url,
                    "N8N_API_KEY": n8n_key or "YOUR_N8N_API_KEY",
                    "WEBHOOK_SECURITY_MODE": "moderate",
                    "N8N_MCP_TELEMETRY_DISABLED": "true",
                },
            }
        }
    }
    Path(".mcp.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    console.print("  [green]✓ .mcp.json written[/]")


def _claude_desktop_snippet(n8n_url: str, n8n_key: str) -> str:
    """Return the JSON snippet users need to add to Claude Desktop config."""
    return json.dumps({
        "mcpServers": {
            "n8n-mcp": {
                "command": "npx",
                "args": ["n8n-mcp"],
                "env": {
                    "MCP_MODE": "stdio",
                    "LOG_LEVEL": "error",
                    "DISABLE_CONSOLE_OUTPUT": "true",
                    "N8N_API_URL": n8n_url,
                    "N8N_API_KEY": n8n_key or "YOUR_N8N_API_KEY",
                    "WEBHOOK_SECURITY_MODE": "moderate",
                    "N8N_MCP_TELEMETRY_DISABLED": "true",
                },
            }
        }
    }, indent=2)


# ── Main CLI ───────────────────────────────────────────────────────────────

@click.command("configure-workflow")
@click.option("--deploy", is_flag=True, help="Deploy to n8n after generating")
@click.option("--skip-prereqs", is_flag=True, help="Skip Node.js / npx checks")
def configure_workflow(deploy: bool, skip_prereqs: bool):
    """
    Interactive wizard: n8n-mcp · n8n-skills · Meta WhatsApp · Workflow deploy.

    Covers:\n
      1. Node.js / n8n-mcp / n8n-skills prerequisites\n
      2. n8n connection + API key\n
      3. .mcp.json + Claude Desktop MCP config\n
      4. n8n-skills plugin installation\n
      5. Meta WhatsApp Cloud API (free) + Anthropic keys\n
      6. Workflow generation with n8n-mcp validation\n
      7. One-click deploy to n8n
    """
    asyncio.run(_wizard(deploy, skip_prereqs))


async def _wizard(deploy: bool, skip_prereqs: bool):
    console.print(Panel(
        "[bold cyan]PG Accountant — Full Setup Wizard[/]\n\n"
        "Integrates:\n"
        "  • [link=https://github.com/czlonkowski/n8n-mcp]github.com/czlonkowski/n8n-mcp[/link]"
        "  — MCP server exposing 1,084 n8n nodes + 2,700 templates\n"
        "  • [link=https://github.com/czlonkowski/n8n-skills]github.com/czlonkowski/n8n-skills[/link]"
        "  — Claude Code skills for n8n workflow building",
        expand=False,
    ))

    # ── 1. Prerequisites ───────────────────────────────────────────────────
    if not skip_prereqs:
        console.rule("[bold]Step 1 — Prerequisites[/]")
        await _check_prerequisites()

    # ── 2. n8n connection ──────────────────────────────────────────────────
    console.rule("[bold]Step 2 — n8n Connection[/]")
    n8n_url = questionary.text(
        "n8n base URL:",
        default=os.getenv("N8N_BASE_URL", "http://localhost:5678"),
    ).ask()
    n8n_key = questionary.password(
        "n8n API Key (n8n Settings → API → Create new key):",
        default=os.getenv("N8N_API_KEY", ""),
    ).ask()

    _save_env("N8N_BASE_URL", n8n_url)
    _save_env("N8N_API_URL",  n8n_url)   # n8n-mcp uses N8N_API_URL
    if n8n_key:
        _save_env("N8N_API_KEY", n8n_key)

    from src.n8n_hooks.mcp_client import N8NMCPClient
    rest = N8NMCPClient()
    rest.base_url = n8n_url
    rest.api_key  = n8n_key
    rest._headers["X-N8N-API-KEY"] = n8n_key

    n8n_ok = await rest.ping()
    console.print(
        f"  [green]✓ n8n reachable[/]" if n8n_ok
        else f"  [yellow]⚠ n8n not reachable — workflows saved locally only[/]"
    )
    if not n8n_ok:
        deploy = False

    # ── 3. .mcp.json + Claude Desktop config ──────────────────────────────
    console.rule("[bold]Step 3 — Claude Code MCP Configuration[/]")
    console.print(
        "  [dim]n8n-mcp gives Claude Code direct access to n8n's node database,\n"
        "  2,700 workflow templates, and the ability to create/deploy workflows.[/]"
    )
    if questionary.confirm("Write .mcp.json for this project?", default=True).ask():
        _write_mcp_json(n8n_url, n8n_key)

    # Show Claude Desktop snippet
    os_name = platform.system()
    cfg_path = {
        "Darwin":  "~/Library/Application Support/Claude/claude_desktop_config.json",
        "Windows": "%APPDATA%\\Claude\\claude_desktop_config.json",
    }.get(os_name, "~/.config/Claude/claude_desktop_config.json")
    console.print(f"\n  [dim]Also add to Claude Desktop config ({cfg_path}):[/]")
    console.print(Syntax(_claude_desktop_snippet(n8n_url, n8n_key), "json", theme="monokai"))

    # ── 4. n8n-skills plugin ───────────────────────────────────────────────
    console.rule("[bold]Step 4 — n8n-skills Claude Code Plugin[/]")
    console.print(
        "  [dim]n8n-skills teaches Claude 7 specialised skills:\n"
        "  expression syntax, workflow patterns, node configuration,\n"
        "  JavaScript/Python code nodes, validation, and MCP tool usage.[/]"
    )
    await _setup_n8n_skills()

    # ── 5. API server URL ──────────────────────────────────────────────────
    console.rule("[bold]Step 5 — PG Accountant API URL[/]")
    api_url = questionary.text(
        "PG Accountant API URL (must be reachable from n8n):",
        default=os.getenv("DASHBOARD_BASE_URL", "http://localhost:8000"),
    ).ask()
    _save_env("DASHBOARD_BASE_URL", api_url)

    webhook_secret = os.getenv("N8N_WEBHOOK_SECRET") or secrets.token_hex(16)
    _save_env("N8N_WEBHOOK_SECRET", webhook_secret)
    console.print(f"  [green]✓ Webhook secret set[/] (saved to .env)")

    # ── 6. Meta WhatsApp Cloud API (free, no Twilio) ───────────────────────
    console.rule("[bold]Step 6 — Meta WhatsApp Cloud API (FREE)[/]")
    console.print(
        "  [dim]No Twilio account needed — Meta's own API is free (1,000 conversations/month).\n"
        "  Get your credentials from developers.facebook.com → Your App → WhatsApp → API Setup.[/]"
    )
    if questionary.confirm("Configure Meta WhatsApp Cloud API?", default=True).ask():
        wa_token    = questionary.password(
            "Meta WhatsApp Token (Temporary or Permanent):",
            default=os.getenv("WHATSAPP_TOKEN", ""),
        ).ask()
        wa_phone_id = questionary.text(
            "Phone Number ID (from Meta WhatsApp API Setup page):",
            default=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
        ).ask()
        wa_verify   = questionary.text(
            "Verify Token (any string you choose — used once for webhook registration):",
            default=os.getenv("WHATSAPP_VERIFY_TOKEN", "pg-accountant-verify"),
        ).ask()
        if wa_token:    _save_env("WHATSAPP_TOKEN",           wa_token)
        if wa_phone_id: _save_env("WHATSAPP_PHONE_NUMBER_ID", wa_phone_id)
        if wa_verify:   _save_env("WHATSAPP_VERIFY_TOKEN",    wa_verify)
        console.print("  [green]✓ Meta WhatsApp config saved to .env[/]")
        console.print("\n  [dim]Next — register your webhook URL in Meta App Dashboard:[/]")
        console.print("  [cyan]  Callback URL : https://<your-ngrok-url>/webhook/whatsapp[/]")
        console.print(f"  [cyan]  Verify Token : {wa_verify or 'pg-accountant-verify'}[/]")
        console.print("  [dim]  Subscribe to the [bold]messages[/] field, then click Verify & Save.[/]")

    # ── 7. Anthropic API key ───────────────────────────────────────────────
    console.rule("[bold]Step 7 — Anthropic API Key[/]")
    console.print("  [dim]Used for ~3% of transactions (unknown merchants + ambiguous WhatsApp messages).[/]")
    ant_key = questionary.password("Anthropic API Key:", default=os.getenv("ANTHROPIC_API_KEY", "")).ask()
    if ant_key:
        _save_env("ANTHROPIC_API_KEY", ant_key)
        console.print("  [green]✓ Anthropic key saved[/]")

    # ── 8. Generate + validate workflows ──────────────────────────────────
    console.rule("[bold]Step 8 — Generate Workflows[/]")
    selected = questionary.checkbox(
        "Select workflows to generate:",
        choices=[
            questionary.Choice("WhatsApp Handler  (Meta Cloud API → PG API → reply)", value="whatsapp",       checked=True),
            questionary.Choice("File Ingestion    (poll data/raw/ every 15 min)", value="ingestion",      checked=True),
            questionary.Choice("Daily Reconcile   (11 PM IST cron)",              value="reconciliation", checked=True),
        ]
    ).ask()

    from src.n8n_hooks.workflow_generator import N8NWorkflowGenerator
    from src.n8n_hooks.n8nmcp_tools import get_workflow_manager

    gen = N8NWorkflowGenerator()
    gen.api_server = api_url
    gen.base_url   = n8n_url

    mgr = get_workflow_manager()
    mgr._generator = gen

    saved: list[dict] = []
    builders = {
        "whatsapp":       ("whatsapp_handler.json",      gen.create_whatsapp_workflow),
        "ingestion":      ("file_ingestion.json",         gen.create_ingestion_workflow),
        "reconciliation": ("daily_reconciliation.json",   gen.create_reconciliation_workflow),
    }

    for key in selected:
        filename, builder = builders[key]
        wf = builder()
        validation_note = ""

        if mgr.is_n8n_mcp_available():
            v = mgr.validate_workflow(wf)
            if v.get("valid", True):
                validation_note = "[green](✓ n8n-mcp validated)[/]"
            else:
                validation_note = f"[red](⚠ {v.get('errors', [])})[/]"
        else:
            validation_note = "[dim](n8n-mcp not installed — skipping validation)[/]"

        path = gen.save_workflow(wf, filename)
        saved.append({"name": wf["name"], "path": str(path), "note": validation_note})
        console.print(f"  [green]✓[/] {wf['name']} → {path.name}  {validation_note}")

    # ── 9. Deploy ──────────────────────────────────────────────────────────
    if deploy and n8n_ok and saved:
        console.rule("[bold]Step 9 — Deploy to n8n[/]")
        if questionary.confirm(f"Deploy {len(saved)} workflow(s) to {n8n_url}?").ask():
            results = await rest.deploy_all("./workflows/n8n")
            t = Table(title="Deployed Workflows")
            t.add_column("Name", style="cyan")
            t.add_column("ID",   style="green")
            t.add_column("Active")
            for r in results:
                t.add_row(r.get("name",""), str(r.get("id","")), "✓" if r.get("active") else "○")
            console.print(t)
    elif not deploy:
        console.print("\n  [dim]Re-run with [bold]--deploy[/] to push workflows to n8n.[/]")

    # ── Done ───────────────────────────────────────────────────────────────
    console.rule()
    console.print("\n[bold green]✓ All done![/]\n")
    console.print("Next steps:")
    console.print("  [bold]python -m cli.start_api[/]              → start the API on :8000")
    console.print("  [bold]python -m cli.ingest_file <file>[/]     → ingest a payment file")
    console.print("  [bold]python -m cli.run_reconciliation[/]     → monthly reconciliation")
    console.print("  [bold]python -m cli.generate_report --open[/] → open dashboard in browser")
    console.print("\nSee [bold]DEPLOYMENT.md[/] for the complete setup guide.")


# ── Step helpers ───────────────────────────────────────────────────────────

async def _check_prerequisites():
    node_ok, node_v = _run(["node", "--version"])
    npx_ok,  npx_v  = _run(["npx", "--version"])

    for name, ok, version in [("Node.js", node_ok, node_v), ("npx", npx_ok, npx_v)]:
        if ok:
            console.print(f"  [green]✓ {name}[/] ({version})")
        else:
            console.print(f"  [red]✗ {name} not found[/] — install from https://nodejs.org")
            raise SystemExit(1)

    # n8n-mcp
    mcp_ok, _ = _run(["npx", "--yes", "n8n-mcp", "--version"], timeout=30)
    if mcp_ok:
        console.print("  [green]✓ n8n-mcp[/] (cached via npx)")
    else:
        console.print("  [yellow]⚠ n8n-mcp not cached[/]")
        if questionary.confirm("Pre-install n8n-mcp globally now? (~30s)", default=True).ask():
            ok2, out = _run(["npm", "install", "-g", "n8n-mcp"], timeout=180)
            console.print(f"  {'[green]✓[/]' if ok2 else '[yellow]⚠[/]'} {out}")


async def _setup_n8n_skills():
    method = questionary.select(
        "Install n8n-skills:",
        choices=[
            questionary.Choice(
                "Claude Code  →  /plugin install czlonkowski/n8n-skills",
                value="cc"
            ),
            questionary.Choice(
                "Marketplace  →  /plugin marketplace add czlonkowski/n8n-skills",
                value="market"
            ),
            questionary.Choice(
                "Manual copy  →  git clone + cp to ~/.claude/skills/",
                value="manual"
            ),
            questionary.Choice("Skip for now", value="skip"),
        ]
    ).ask()

    if method in ("cc", "market"):
        cmd = (
            "/plugin install czlonkowski/n8n-skills"
            if method == "cc"
            else "/plugin marketplace add czlonkowski/n8n-skills"
        )
        console.print("\n  Run this in your Claude Code session:")
        console.print(Syntax(cmd, "bash", theme="monokai"))
        questionary.confirm("  Press Enter when done (or to skip)", default=True).ask()

    elif method == "manual":
        console.print("\n  Run in your terminal:")
        console.print(Syntax(
            "git clone https://github.com/czlonkowski/n8n-skills.git /tmp/n8n-skills\n"
            "cp -r /tmp/n8n-skills/skills/* ~/.claude/skills/",
            "bash", theme="monokai"
        ))
        questionary.confirm("  Press Enter when done (or to skip)", default=True).ask()

    else:
        console.print("  [dim]Skipped. Install later from github.com/czlonkowski/n8n-skills[/]")


if __name__ == "__main__":
    configure_workflow()
