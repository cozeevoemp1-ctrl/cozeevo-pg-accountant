"""
PG Accountant — FastAPI Application Entry Point.

Start with:
    python -m cli.start_api
    uvicorn main:app --reload
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

load_dotenv()

# ── Security middleware — block external access to /api/* ──────────────────
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

class LocalOnlyMiddleware(BaseHTTPMiddleware):
    """
    Allow /webhook/* from anywhere (Meta Cloud API needs this).
    Block /api/* and /docs from the public internet — localhost only.
    This protects against someone finding your ngrok URL and abusing it.
    """
    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path

        # Webhook, health, and dashboard are public
        # Dashboard API is token-protected at the endpoint level
        if (path.startswith("/webhook") or path == "/healthz" or path == "/"
                or path.startswith("/dashboard") or path.startswith("/api/dashboard")
                or path.startswith("/static")):
            return await call_next(request)

        # Everything else (/api/*, /docs, /redoc, /openapi.json) — localhost only
        client_host = request.client.host if request.client else ""
        is_local = client_host in ("127.0.0.1", "::1", "localhost")
        if not is_local:
            return StarletteResponse("Forbidden", status_code=403)

        return await call_next(request)


# ── Lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/pg_accountant.db")
    from src.database.db_manager import init_db
    await init_db(db_url)
    logger.info("✓ Database initialized")

    # Dashboard temp-file cleanup (existing lightweight scheduler)
    from src.dashboard.cleanup import start_cleanup_scheduler
    cleanup_scheduler = start_cleanup_scheduler()

    # Business scheduler — rent reminders, reconciliation, backups (persisted in DB)
    from src.scheduler import start_scheduler, stop_scheduler
    pg_scheduler = start_scheduler()

    yield

    # Shutdown
    stop_scheduler(pg_scheduler)
    cleanup_scheduler.shutdown(wait=False)
    logger.info("PG Accountant API shutting down.")


# ── App ────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PG Accountant",
    description="AI-powered bookkeeping for PG businesses",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,      # disable /docs from public internet
    redoc_url=None,     # disable /redoc from public internet
    openapi_url=None,   # disable /openapi.json from public internet
)

app.add_middleware(LocalOnlyMiddleware)

# ── Routers ────────────────────────────────────────────────────────────────

from src.whatsapp.webhook_handler import router as whatsapp_router
app.include_router(whatsapp_router)

from src.api.dashboard_router import router as dashboard_router
app.include_router(dashboard_router)

from src.whatsapp.chat_api import router as chat_router
app.include_router(chat_router)

from src.api.reminder_router import router as reminder_router
app.include_router(reminder_router)

# ── Ingest API ─────────────────────────────────────────────────────────────

from fastapi import APIRouter, UploadFile, File, Form
import shutil, uuid, asyncio

ingest_router = APIRouter(prefix="/api/ingest", tags=["ingestion"])

@ingest_router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a CSV/PDF for ingestion."""
    raw_dir = Path(os.getenv("DATA_RAW_DIR", "./data/raw"))
    raw_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "").suffix.lower() or ".csv"
    filename = f"upload_{uuid.uuid4().hex[:8]}{ext}"
    out_path = raw_dir / filename

    with out_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # Ingest in background
    asyncio.create_task(_bg_ingest(str(out_path)))
    return {"status": "queued", "file": filename}

@ingest_router.post("/scan")
async def scan_raw_folder():
    """Scan data/raw/ for new unprocessed files and ingest them."""
    raw_dir     = Path(os.getenv("DATA_RAW_DIR", "./data/raw"))
    proc_dir    = Path(os.getenv("DATA_PROCESSED_DIR", "./data/processed"))
    proc_dir.mkdir(parents=True, exist_ok=True)

    files = list(raw_dir.glob("*.csv")) + list(raw_dir.glob("*.pdf"))
    results = []
    for f in files:
        try:
            await _bg_ingest(str(f))
            shutil.move(str(f), str(proc_dir / f.name))
            results.append({"file": f.name, "status": "ingested"})
        except Exception as e:
            results.append({"file": f.name, "status": "error", "error": str(e)})
    return {"ingested": len([r for r in results if r["status"] == "ingested"]), "results": results}

async def _bg_ingest(file_path: str):
    from src.parsers.dispatcher import parse_file
    from src.rules.deduplication import batch_deduplicate
    from src.rules.categorization_rules import classify_batch
    from src.database.db_manager import upsert_transaction, get_category_by_name

    raw = parse_file(file_path)
    unique, _ = batch_deduplicate(raw)
    classified = classify_batch(unique)

    for txn in classified:
        cat = await get_category_by_name(txn.get("category", "Miscellaneous"))
        txn_clean = {k: txn.get(k) for k in [
            "date", "amount", "txn_type", "source", "description",
            "upi_reference", "merchant", "unique_hash", "raw_data",
            "ai_classified", "confidence",
        ]}
        if cat:
            txn_clean["category_id"] = cat.id
        await upsert_transaction(txn_clean)

app.include_router(ingest_router)

# ── Reconciliation API ─────────────────────────────────────────────────────

recon_router = APIRouter(prefix="/api/reconcile", tags=["reconciliation"])

from pydantic import BaseModel
from typing import Optional

class ReconcileRequest(BaseModel):
    period: str = "monthly"
    year:   Optional[int] = None
    month:  Optional[int] = None

@recon_router.post("")
async def reconcile(req: ReconcileRequest):
    from src.reports.reconciliation import ReconciliationEngine
    from datetime import datetime
    engine = ReconciliationEngine()
    now = datetime.now()
    if req.period == "monthly":
        return await engine.monthly_reconcile(req.year or now.year, req.month or now.month)
    elif req.period == "weekly":
        return await engine.weekly_reconcile()
    return await engine.daily_reconcile()

app.include_router(recon_router)

# ── Report API ─────────────────────────────────────────────────────────────

report_router = APIRouter(prefix="/api/report", tags=["reports"])

@report_router.post("/dashboard")
async def generate_dashboard(req: ReconcileRequest):
    from src.reports.reconciliation import ReconciliationEngine
    from src.reports.report_generator import ReportGenerator
    from datetime import datetime
    engine = ReconciliationEngine()
    gen    = ReportGenerator()
    now    = datetime.now()
    data   = await engine.monthly_reconcile(req.year or now.year, req.month or now.month)
    url    = await gen.generate_dashboard(data, req.period)
    return {"url": url}

app.include_router(report_router)

# ── Dashboard file serving ────────────────────────────────────────────────

# Legacy generated-report dashboards
dashboard_dir = Path(os.getenv("DASHBOARD_DIR", "./dashboards"))
dashboard_dir.mkdir(parents=True, exist_ok=True)
app.mount("/dashboards", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboards")

# Static assets (source-controlled)
static_dir = Path("./static")
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/dashboard")
async def dashboard_page():
    return FileResponse(str(static_dir / "dashboard.html"))

# ── Pending entity approval API ───────────────────────────────────────────

entity_router = APIRouter(prefix="/api/entities", tags=["master-data"])

@entity_router.get("/pending")
async def get_pending():
    from src.database.db_manager import get_pending_entities
    items = await get_pending_entities()
    return [{"id": p.id, "type": p.entity_type, "data": p.raw_data} for p in items]

@entity_router.post("/{entity_id}/approve")
async def approve(entity_id: int):
    from src.database.db_manager import approve_pending_entity
    result = await approve_pending_entity(entity_id)
    if not result:
        raise HTTPException(404, "Pending entity not found")
    return result

@entity_router.post("/{entity_id}/reject")
async def reject(entity_id: int):
    from src.database.db_manager import reject_pending_entity
    await reject_pending_entity(entity_id)
    return {"status": "rejected"}

app.include_router(entity_router)

# ── Test utilities (TEST_MODE=1 only) ────────────────────────────────────

if os.getenv("TEST_MODE") == "1":
    from fastapi import Depends
    from sqlalchemy import text
    from src.database.db_manager import get_db_session

    test_router = APIRouter(prefix="/api/test", tags=["test"])

    @test_router.post("/clear-pending")
    async def clear_pending(body: Optional[dict] = None, session=Depends(get_db_session)):
        """Delete pending actions for a phone (or all) — TEST_MODE only."""
        phone = body.get("phone") if body else None
        if phone:
            # Normalize: strip leading + and country code
            normalized = phone.lstrip("+")
            if normalized.startswith("91") and len(normalized) == 12:
                normalized = normalized[2:]
            await session.execute(
                text("DELETE FROM pending_actions WHERE phone = :phone OR phone = :raw"),
                {"phone": normalized, "raw": phone},
            )
        else:
            await session.execute(text("DELETE FROM pending_actions"))
        await session.commit()
        return {"status": "cleared", "phone": phone or "all"}

    app.include_router(test_router)

# ── Health check ───────────────────────────────────────────────────────────

@app.get("/healthz")
async def health():
    return {"status": "ok", "service": "pg-accountant"}


@app.get("/")
async def root():
    return {
        "service": "PG Accountant API",
        "version": "1.0.0",
        "docs": "/docs",
    }
