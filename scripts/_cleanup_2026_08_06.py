"""One-off: execute approved items from docs/CLEANUP_DRY_RUN.md (Kiran approved 2026-08-06).

Scope (reversible only — backup JSON written first):
  A1  void duplicate payments 21867, 21450, 21829 (is_void=true, reversible)
  B1  Sujal t1226 phantom Jul'26 rent_schedule -> status 'na'
  E   10 stale pending_review onboarding sessions on active tenancies -> approved
  F1  session 279 (Harshit no-show) -> cancelled
  F2  t1143 Devamsh: active but checkout_date 2026-06-07 -> exited (only if no activity after 10 Jun)
  F3  t845 Satish: exited, checkout_date NULL -> fill from checkout_records if present

NOT in scope (still need Kiran input): A2 mirror pairs, A3 frozen t871, C room 402.

Usage:  python scripts/_cleanup_2026_08_06.py            # inspect + write backup, no changes
        python scripts/_cleanup_2026_08_06.py --write    # execute in one transaction
Rollback: scripts/_rollback via backup scripts/_backup_cleanup_2026_08_06.json
"""
import sys, os, json, asyncio
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

WRITE = "--write" in sys.argv
BACKUP = os.path.join(os.path.dirname(__file__), "_backup_cleanup_2026_08_06.json")
CHANGED_BY = "cleanup_2026_08_06 (Kiran-approved dry-run execution)"

VOID_PAYMENTS = {21867: 21866, 21450: 21449, 21829: 21676}  # void_id -> kept_id
STALE_SESSIONS = [214, 223, 226, 227, 229, 230, 235, 249, 253, 254]


def j(rows):
    return [{k: (v.isoformat() if isinstance(v, (datetime, date)) else str(v) if v is not None and not isinstance(v, (int, float, bool)) else v)
             for k, v in dict(r._mapping).items()} for r in rows]


async def main():
    eng = create_async_engine(os.environ["DATABASE_URL"])
    backup = {"executed_at": None, "write_mode": WRITE}
    async with eng.connect() as c:
        pm = (await c.execute(text("SELECT * FROM payments WHERE id = ANY(:ids)"),
                              {"ids": list(VOID_PAYMENTS) + list(VOID_PAYMENTS.values())})).fetchall()
        backup["payments"] = j(pm)
        rs = (await c.execute(text(
            "SELECT * FROM rent_schedule WHERE tenancy_id=1226 AND period_month='2026-07-01'"))).fetchall()
        backup["rent_schedule_1226"] = j(rs)
        ob = (await c.execute(text("SELECT id,status,tenancy_id,tenant_data::jsonb->>'name' AS tenant_name FROM onboarding_sessions WHERE id = ANY(:ids)"),
                              {"ids": STALE_SESSIONS + [279]})).fetchall()
        backup["onboarding_sessions"] = j(ob)
        t1143 = (await c.execute(text("SELECT id,status,checkin_date,checkout_date,org_id FROM tenancies WHERE id=1143"))).fetchall()
        backup["tenancy_1143"] = j(t1143)
        act1143 = (await c.execute(text(
            "SELECT count(*) FROM payments WHERE tenancy_id=1143 AND is_void=false AND payment_date > '2026-06-10'"))).scalar()
        backup["t1143_payments_after_jun10"] = act1143
        t845 = (await c.execute(text("SELECT id,status,checkin_date,checkout_date,org_id FROM tenancies WHERE id=845"))).fetchall()
        backup["tenancy_845"] = j(t845)
        cr845 = (await c.execute(text(
            "SELECT * FROM checkout_records WHERE tenancy_id=845"))).fetchall()
        backup["checkout_records_845"] = j(cr845)

    with open(BACKUP, "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2, default=str)
    print(f"Backup written: {BACKUP}")
    print(f"  payments rows: {len(backup['payments'])} (need {len(VOID_PAYMENTS)*2})")
    print(f"  RS 1226 Jul rows: {len(backup['rent_schedule_1226'])}")
    print(f"  sessions found: {[(r['id'], r['status']) for r in backup['onboarding_sessions']]}")
    print(f"  t1143: {backup['tenancy_1143']} | payments after 10 Jun: {act1143}")
    print(f"  t845: {backup['tenancy_845']} | checkout_records: {len(backup['checkout_records_845'])}")

    if not WRITE:
        print("\nDRY MODE — nothing changed. Re-run with --write to execute.")
        return

    async with eng.begin() as c:
        # Voids target Jun/Jul period_month rows — historical-write freeze needs the
        # explicit escape hatch (Kiran approved these specific voids 2026-08-06).
        await c.execute(text("SET LOCAL app.allow_historical_write = 'true'"))

        async def audit(entity_type, entity_id, entity_name, field, old, new, org_id):
            await c.execute(text("""
                INSERT INTO audit_log (changed_by, entity_type, entity_id, entity_name, field,
                                       old_value, new_value, source, org_id, created_at)
                VALUES (:by, :et, :eid, :en, :f, :o, :n, 'script', :org, NOW())"""),
                {"by": CHANGED_BY, "et": entity_type, "eid": entity_id, "en": entity_name,
                 "f": field, "o": str(old), "n": str(new), "org": org_id})

        # A1 — void duplicate payments
        for void_id, kept_id in VOID_PAYMENTS.items():
            row = (await c.execute(text(
                "SELECT p.id, p.amount, p.tenancy_id, ty.org_id, t.name FROM payments p "
                "JOIN tenancies ty ON ty.id=p.tenancy_id JOIN tenants t ON t.id=ty.tenant_id "
                "WHERE p.id=:i AND p.is_void=false"), {"i": void_id})).fetchone()
            if not row:
                print(f"  SKIP payment {void_id}: not found or already void")
                continue
            await c.execute(text(
                "UPDATE payments SET is_void=true, "
                "notes=coalesce(notes,'')||' | voided: duplicate of '||:k||' (cleanup 2026-08-06)' "
                "WHERE id=:i"), {"i": void_id, "k": str(kept_id)})
            await audit("payment", void_id, f"{row.name} (tenancy {row.tenancy_id})",
                        "is_void", "false", f"true (dup of {kept_id})", row.org_id)
            print(f"  VOIDED payment {void_id} (₹{row.amount}, dup of {kept_id})")

        # B1 — phantom Jul RS on exited tenancy 1226
        r = (await c.execute(text(
            "SELECT rs.id, rs.status, ty.org_id FROM rent_schedule rs JOIN tenancies ty ON ty.id=rs.tenancy_id "
            "WHERE rs.tenancy_id=1226 AND rs.period_month='2026-07-01' AND rs.status='pending'"))).fetchone()
        if r:
            await c.execute(text("UPDATE rent_schedule SET status='na' WHERE id=:i"), {"i": r.id})
            await audit("rent_schedule", r.id, "Sujal Jaiswal t1226 Jul'26 phantom due",
                        "status", "pending", "na", r.org_id)
            print(f"  RS {r.id} (t1226 Jul) pending -> na")
        else:
            print("  SKIP RS t1226 Jul: no pending row")

        # E — stale pending_review sessions on active tenancies -> approved
        rows = (await c.execute(text(
            "SELECT obs.id, obs.status, obs.tenant_data::jsonb->>'name' AS tenant_name, ty.org_id FROM onboarding_sessions obs "
            "JOIN tenancies ty ON ty.id=obs.tenancy_id "
            "WHERE obs.id = ANY(:ids) AND obs.status='pending_review' AND ty.status='active'"),
            {"ids": STALE_SESSIONS})).fetchall()
        for s in rows:
            await c.execute(text(
                "UPDATE onboarding_sessions SET status='approved', approved_at=NOW() WHERE id=:i"), {"i": s.id})
            await audit("onboarding_session", s.id, s.tenant_name or "?",
                        "status", "pending_review", "approved (tenancy already active; PDF via regen later)", s.org_id)
        print(f"  APPROVED {len(rows)}/{len(STALE_SESSIONS)} stale sessions")

        # F1 — session 279 Harshit -> cancelled
        s = (await c.execute(text(
            "SELECT obs.id, obs.status, obs.tenant_data::jsonb->>'name' AS tenant_name, ty.org_id FROM onboarding_sessions obs "
            "LEFT JOIN tenancies ty ON ty.id=obs.tenancy_id WHERE obs.id=279 AND obs.status='pending_tenant'"))).fetchone()
        if s:
            await c.execute(text("UPDATE onboarding_sessions SET status='cancelled' WHERE id=279"))
            await audit("onboarding_session", 279, s.tenant_name or "Harshit Srivastava",
                        "status", "pending_tenant", "cancelled (32-day stale no-show hold)", s.org_id or 1)
            print("  CANCELLED session 279")
        else:
            print("  SKIP session 279: not pending_tenant")

        # F2 — t1143 Devamsh: exited only if genuinely inactive
        t = (await c.execute(text(
            "SELECT ty.id, ty.status, ty.checkout_date, ty.org_id, t.name FROM tenancies ty "
            "JOIN tenants t ON t.id=ty.tenant_id WHERE ty.id=1143 AND ty.status='active'"))).fetchone()
        n_after = (await c.execute(text(
            "SELECT count(*) FROM payments WHERE tenancy_id=1143 AND is_void=false AND payment_date > '2026-06-10'"))).scalar()
        if t and n_after == 0:
            await c.execute(text("UPDATE tenancies SET status='exited' WHERE id=1143"))
            await audit("tenancy", 1143, t.name, "status",
                        "active", "exited (checkout_date 2026-06-07, no activity since)", t.org_id)
            print("  t1143 Devamsh active -> exited")
        else:
            print(f"  SKIP t1143: active={bool(t)}, payments after 10 Jun={n_after} (manual review)")

        # F3 — t845 Satish: fill checkout_date from checkout_records
        cr = (await c.execute(text(
            "SELECT actual_exit_date AS checkout_date FROM checkout_records WHERE tenancy_id=845 AND actual_exit_date IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"))).fetchone()
        if cr:
            t = (await c.execute(text(
                "SELECT ty.org_id, t.name FROM tenancies ty JOIN tenants t ON t.id=ty.tenant_id WHERE ty.id=845"))).fetchone()
            await c.execute(text("UPDATE tenancies SET checkout_date=:d WHERE id=845 AND checkout_date IS NULL"),
                            {"d": cr.checkout_date})
            await audit("tenancy", 845, t.name, "checkout_date", "NULL", str(cr.checkout_date), t.org_id)
            print(f"  t845 checkout_date <- {cr.checkout_date}")
        else:
            print("  SKIP t845: no checkout_record with date (needs Kiran/sheet)")

    await eng.dispose()
    print("\nDONE — all changes committed in one transaction, audit_log written per change.")

asyncio.run(main())
