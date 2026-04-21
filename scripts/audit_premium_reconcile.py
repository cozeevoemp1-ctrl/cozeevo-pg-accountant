"""One-off: reconcile premium tenants between source Google Sheet and DB.

Report only — no writes.
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from dotenv import load_dotenv
import gspread
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.database.db_manager import init_engine, get_session
from src.database.models import Tenancy, Tenant, Room, TenancyStatus, SharingType

ROOT = Path(__file__).resolve().parents[1]
SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
TAB = "Long term"
CREDS = ROOT / "credentials" / "gsheets_service_account.json"
OUT = ROOT / "docs" / "audit_premium_2026-04-21.md"


def norm_phone(p: str) -> str:
    if not p:
        return ""
    digits = re.sub(r"\D", "", str(p))
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


def read_sheet():
    gc = gspread.service_account(filename=str(CREDS))
    ws = gc.open_by_key(SHEET_ID).worksheet(TAB)
    rows = ws.get_all_values()
    header = rows[0]
    # Confirmed columns by index per task: M=sharing (12), Q=IN/OUT (16)
    sheet_prem = []
    for idx, r in enumerate(rows[1:], start=2):
        def col(i):
            return r[i].strip() if i < len(r) else ""
        sharing = col(12)
        inout = col(16)
        if "prem" in sharing.lower() and inout.strip().upper() == "CHECKIN":
            # Guess name/phone/room columns — inspect first row to find indices
            sheet_prem.append({
                "row": idx,
                "all": r,
                "sharing": sharing,
                "inout": inout,
            })
    return header, sheet_prem, rows


async def read_db():
    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_URL")
    init_engine(url)
    async with get_session() as s:
        q = (
            select(Tenancy)
            .options(selectinload(Tenancy.tenant), selectinload(Tenancy.room))
            .where(
                Tenancy.status == TenancyStatus.active,
                Tenancy.sharing_type == SharingType.premium,
            )
        )
        res = await s.execute(q)
        out = []
        for t in res.scalars().all():
            out.append({
                "name": t.tenant.name if t.tenant else "",
                "phone": norm_phone(t.tenant.phone if t.tenant else ""),
                "phone_raw": t.tenant.phone if t.tenant else "",
                "room": t.room.room_number if t.room else "",
            })
        return out


async def main():
    header, sheet_prem, all_rows = read_sheet()
    print("=== SHEET HEADER ===")
    for i, h in enumerate(header):
        print(f"  [{i}] {h}")

    # Try to identify name/phone/room columns from header
    def find(names):
        for i, h in enumerate(header):
            hl = h.strip().lower()
            for n in names:
                if n in hl:
                    return i
        return None

    name_col = find(["name"])
    phone_col = find(["phone", "mobile", "contact"])
    room_col = find(["room"])
    print(f"name_col={name_col} phone_col={phone_col} room_col={room_col}")

    sheet_records = []
    for sp in sheet_prem:
        r = sp["all"]
        def col(i):
            return r[i].strip() if i is not None and i < len(r) else ""
        sheet_records.append({
            "row": sp["row"],
            "name": col(name_col),
            "phone": norm_phone(col(phone_col)),
            "phone_raw": col(phone_col),
            "room": col(room_col),
            "sharing": sp["sharing"],
        })

    print(f"\n=== SHEET PREMIUM CHECKIN ({len(sheet_records)}) ===")
    for s in sheet_records:
        print(f"  row {s['row']:>3} | {s['name']:<30} | {s['phone_raw']:<15} | room {s['room']:<8} | {s['sharing']}")

    db_records = await read_db()
    print(f"\n=== DB PREMIUM ACTIVE ({len(db_records)}) ===")
    for d in db_records:
        print(f"  {d['name']:<30} | {d['phone_raw']:<15} | room {d['room']}")

    sheet_phones = {s["phone"] for s in sheet_records if s["phone"]}
    db_phones = {d["phone"] for d in db_records if d["phone"]}

    only_sheet = sheet_phones - db_phones
    only_db = db_phones - sheet_phones

    sheet_by_phone = {s["phone"]: s for s in sheet_records}
    db_by_phone = {d["phone"]: d for d in db_records}

    print(f"\n=== ONLY IN SHEET ({len(only_sheet)}) ===")
    for p in only_sheet:
        s = sheet_by_phone[p]
        print(f"  row {s['row']} | {s['name']} | {p} | room {s['room']} | sharing={s['sharing']}")

    print(f"\n=== ONLY IN DB ({len(only_db)}) ===")
    for p in only_db:
        d = db_by_phone[p]
        print(f"  {d['name']} | {p} | room {d['room']}")

    # Markdown report
    lines = []
    lines.append("# Premium Tenant Reconciliation — 2026-04-21\n")
    lines.append("Source sheet: `Cozeevo Operations v2` → tab `Long term`\n")
    lines.append(f"Sheet ID: `{SHEET_ID}`\n\n")
    lines.append("## Counts\n")
    lines.append(f"- Sheet (CHECKIN + sharing contains 'prem'): **{len(sheet_records)}**\n")
    lines.append(f"- DB (status=active, sharing_type=premium): **{len(db_records)}**\n")
    lines.append(f"- Kiran's expected count: **22**\n\n")

    lines.append("## Sheet premium CHECKIN rows\n\n")
    lines.append("| Row | Name | Phone | Room | Sharing |\n|---|---|---|---|---|\n")
    for s in sorted(sheet_records, key=lambda x: x["row"]):
        lines.append(f"| {s['row']} | {s['name']} | {s['phone_raw']} | {s['room']} | {s['sharing']} |\n")

    lines.append("\n## DB premium active tenancies\n\n")
    lines.append("| Name | Phone | Room |\n|---|---|---|\n")
    for d in sorted(db_records, key=lambda x: x["name"]):
        lines.append(f"| {d['name']} | {d['phone_raw']} | {d['room']} |\n")

    lines.append("\n## Mismatches\n\n")
    lines.append(f"### Only in Sheet ({len(only_sheet)}) — sheet says premium, DB doesn't\n\n")
    if only_sheet:
        lines.append("| Sheet Row | Name | Phone | Room | Sharing | Action |\n|---|---|---|---|---|---|\n")
        for p in only_sheet:
            s = sheet_by_phone[p]
            lines.append(f"| {s['row']} | {s['name']} | {s['phone_raw']} | {s['room']} | {s['sharing']} | Verify DB sharing_type — upgrade to premium if sheet is correct |\n")
    else:
        lines.append("_None._\n")

    lines.append(f"\n### Only in DB ({len(only_db)}) — DB says premium, Sheet doesn't\n\n")
    if only_db:
        lines.append("| Name | Phone | Room | Action |\n|---|---|---|---|\n")
        for p in only_db:
            d = db_by_phone[p]
            lines.append(f"| {d['name']} | {d['phone_raw']} | {d['room']} | Verify sheet column M — downgrade DB if sheet is correct |\n")
    else:
        lines.append("_None._\n")

    # Duplicate detection in DB
    from collections import Counter
    phone_counts = Counter(d["phone"] for d in db_records if d["phone"])
    dupes = {p: c for p, c in phone_counts.items() if c > 1}
    lines.append(f"\n## DB duplicates by phone ({len(dupes)})\n\n")
    if dupes:
        lines.append("| Phone | Count | Records |\n|---|---|---|\n")
        for p, c in dupes.items():
            recs = [d for d in db_records if d["phone"] == p]
            detail = "; ".join(f"{r['name']} (room {r['room']}, raw={r['phone_raw']})" for r in recs)
            lines.append(f"| {p} | {c} | {detail} |\n")
    else:
        lines.append("_None._\n")

    lines.append("\n## Suggested correction workflow\n\n")
    lines.append("1. For each row in 'Only in Sheet': check physical room occupancy — is tenant actually alone in a multi-bed room?\n")
    lines.append("2. For each row in 'Only in DB': check sheet column M — typo or genuine downgrade?\n")
    lines.append("3. Once verified, update DB via bot command (never direct SQL). Sheet is read-only mirror.\n")
    lines.append("4. Target: reconcile to Kiran's expected count of 22.\n")

    OUT.write_text("".join(lines), encoding="utf-8")
    print(f"\nReport written: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
