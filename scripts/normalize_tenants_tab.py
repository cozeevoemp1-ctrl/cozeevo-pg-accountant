"""
scripts/normalize_tenants_tab.py
==================================
Rewrite every active/no_show tenant in the TENANTS tab using the canonical
format (phone +91XXXXXXXXXX, dates dd/mm/yyyy, Title-Case categoricals,
short building names). Uses sync_tenant_all_fields which batch-updates
only changed cells.

Usage:
    python scripts/normalize_tenants_tab.py
"""
import asyncio
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from src.database.db_manager import init_engine, get_session
from src.database.models import Tenancy, TenancyStatus


async def main():
    init_engine(os.environ["DATABASE_URL"])
    from src.integrations.gsheets import sync_tenant_all_fields

    async with get_session() as s:
        tenant_ids = (await s.execute(
            select(Tenancy.tenant_id).where(
                Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show])
            ).distinct()
        )).scalars().all()

    print(f"Normalising {len(tenant_ids)} tenants...", flush=True)
    total_cells = 0
    errors = 0
    for i, tid in enumerate(tenant_ids, 1):
        r = await sync_tenant_all_fields(tid)
        if r.get("success"):
            total_cells += r.get("tenants_written", 0)
        else:
            errors += 1
            print(f"  [err] tenant {tid}: {r.get('error')}")
        if i % 25 == 0:
            print(f"  progress: {i}/{len(tenant_ids)}  cells written so far: {total_cells}")
    print(f"Done. Cells changed: {total_cells}  Errors: {errors}")


if __name__ == "__main__":
    asyncio.run(main())
