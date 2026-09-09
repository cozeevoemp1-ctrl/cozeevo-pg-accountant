"""
One-off: void the duplicate Rs.13,000 advance on Hasini Anugandula (Room 620).

What happened (from audit_log, 9 Sep 2026 IST):
    16:36  Lokesh pre-books  -> tenancy 1370, Rs.13,000 advance (payment 22524)
                                phone 8184986823
    16:38  tenancy 1370 CANCELLED (admin, dashboard)
    16:40  Lokesh re-books   -> tenancy 1371, Rs.13,000 advance (payment 22525)
                                phone +918184986826   <- corrected typo
    21:16  tenancy 1371 goes active

The advance on the CANCELLED tenancy was never voided, so the Rs.13,000 she paid
once is counted twice. Her real September money is Rs.13,000 advance + Rs.9,100
rent = Rs.22,100, which matches the source sheet for room 620.

Voids payment 22524 only. Never hard-deletes — sets `is_void = true` and writes an
AuditLog row with field="is_void", which /activity/feed whitelists, so the void
shows up in the activity log. Mirrors src/api/v2/payments.py::void_payment.

Uses raw asyncpg with statement_cache_size=0: the Supabase pooler runs in
transaction mode on 6543 and rejects the prepared statements SQLAlchemy issues.

    py -3 scripts/_void_hasini_620_duplicate.py             # dry run
    py -3 scripts/_void_hasini_620_duplicate.py --write      # apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

PAYMENT_ID = 22524
EXPECT_AMOUNT = 13000
EXPECT_TENANCY = 1370
LIVE_TENANCY = 1371
EXPECT_AFTER = 22100


def _url() -> str:
    return (os.environ["DATABASE_URL"]
            .replace("postgresql+asyncpg://", "postgresql://")
            .replace(":5432/", ":6543/"))


async def main(write: bool) -> int:
    conn = await asyncpg.connect(_url(), statement_cache_size=0)
    try:
        row = await conn.fetchrow("""
            SELECT p.id, p.amount::bigint amt, p.payment_date, p.is_void, p.tenancy_id,
                   p.payment_mode::text mode, p.for_type::text ftype,
                   t.status::text tstatus, tn.name, tn.phone, r.room_number
            FROM payments p
            JOIN tenancies t ON t.id = p.tenancy_id
            JOIN tenants  tn ON tn.id = t.tenant_id
            LEFT JOIN rooms r ON r.id = t.room_id
            WHERE p.id = $1
        """, PAYMENT_ID)

        if row is None:
            print(f"FAIL: payment {PAYMENT_ID} not found")
            return 1

        print(f"payment  id={row['id']} Rs.{row['amt']:,} {row['mode']} {row['ftype']} "
              f"date={row['payment_date']} is_void={row['is_void']}")
        print(f"tenancy  id={row['tenancy_id']} status={row['tstatus']} room={row['room_number']}")
        print(f"tenant   {row['name']} ({row['phone']})")

        # Guards — refuse to touch anything that isn't the row this script was written for.
        if row["amt"] != EXPECT_AMOUNT:
            print(f"FAIL: expected Rs.{EXPECT_AMOUNT}, found Rs.{row['amt']}")
            return 1
        if row["tenancy_id"] != EXPECT_TENANCY:
            print(f"FAIL: expected tenancy {EXPECT_TENANCY}, found {row['tenancy_id']}")
            return 1
        if row["tstatus"] != "cancelled":
            print(f"FAIL: tenancy {row['tenancy_id']} is '{row['tstatus']}', not cancelled — refusing")
            return 1
        if row["is_void"]:
            print("Already voided — nothing to do.")
            return 0

        others = await conn.fetch("""
            SELECT p.id, p.amount::bigint amt, p.for_type::text ftype, p.is_void, p.tenancy_id
            FROM payments p WHERE p.tenancy_id = ANY($1::int[]) ORDER BY p.id
        """, [EXPECT_TENANCY, LIVE_TENANCY])

        print(f"\nPayments across tenancies {EXPECT_TENANCY} (cancelled) + {LIVE_TENANCY} (active):")
        for o in others:
            mark = "   <-- VOIDING" if o["id"] == PAYMENT_ID else ""
            print(f"   id={o['id']} Rs.{o['amt']:>7,} {o['ftype']:8} "
                  f"tenancy={o['tenancy_id']} void={o['is_void']}{mark}")

        after = sum(o["amt"] for o in others if not o["is_void"] and o["id"] != PAYMENT_ID)
        print(f"\nAfter void, live total = Rs.{after:,}  (expected Rs.{EXPECT_AFTER:,})")
        if after != EXPECT_AFTER:
            print("FAIL: post-void total is not what the source sheet says — refusing")
            return 1

        if not write:
            print("\nDRY RUN — nothing written. Re-run with --write to apply.")
            return 0

        async with conn.transaction():
            # Voids are allowed regardless of period freeze, same as the API endpoint.
            await conn.execute("SET LOCAL app.allow_historical_write = 'true'")
            await conn.execute("UPDATE payments SET is_void = true WHERE id = $1", PAYMENT_ID)
            await conn.execute("""
                INSERT INTO audit_log (created_at, changed_by, entity_type, entity_id,
                                       entity_name, field, old_value, new_value,
                                       room_number, source, note, org_id)
                VALUES (now(), $1, 'payment', $2, $3, 'is_void', 'false', 'true', $4, 'script', $5, 1)
            """, "Kiran", PAYMENT_ID, row["name"], row["room_number"],
                 (f"Rs.{EXPECT_AMOUNT} voided — duplicate advance left on cancelled tenancy "
                  f"{EXPECT_TENANCY} after the 9 Sep re-book (phone typo). Paid once, counted twice."))

        check = await conn.fetchrow("SELECT is_void FROM payments WHERE id = $1", PAYMENT_ID)
        aud = await conn.fetchrow(
            "SELECT id, field, note FROM audit_log WHERE entity_type='payment' AND entity_id=$1 "
            "ORDER BY id DESC LIMIT 1", PAYMENT_ID)
        print(f"\nVOIDED payment {PAYMENT_ID}: is_void={check['is_void']}")
        print(f"audit_log id={aud['id']} field={aud['field']} (whitelisted by the activity feed)")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="apply the void (default: dry run)")
    sys.exit(asyncio.run(main(ap.parse_args().write)))
