"""One-off: merge duplicate tenant/tenancy records.

Room 415 — same person, same phone (+919515739255), two tenant rows:
    KEEP   tenancy 901 / tenant 914 "T.Rakesh Chetan"      (active, 7 payments)
    MERGE  tenancy 894 / tenant 897 "Rakesh Thallapally"   (exited, 4 payments)

Room 615 — orphan tenant row left behind when tenancy 1316 was re-pointed:
    KEEP   tenant 1175 "P Sheetal Reddy" (owns tenancy 1316 + docs + payment)
    DELETE tenant 1169 "Sheetal"         (no tenancy, no payments, no documents)

Financial records are never hard-deleted: duplicated payments on 894 are voided
(is_void=True), the unique booking advance is re-pointed to 901, and tenancy 894
is set to `cancelled` (excluded from search / lists / reports everywhere).

Dry run:  python scripts/_merge_duplicate_tenants_415_615.py
Apply:    python scripts/_merge_duplicate_tenants_415_615.py --write
"""
from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from src.database.db_manager import get_session, init_engine  # noqa: E402

KEEP_TENANCY, KEEP_TENANT = 901, 914
DUP_TENANCY, DUP_TENANT = 894, 897

# Payments on 894 that duplicate rows already on 901 → void.
DUP_PAYMENTS = {
    20748: "Apr rent 9,533 — duplicate of payment 21025 on tenancy 901",
    20749: "Deposit 26,000 — duplicate of payment 21026 on tenancy 901",
    20750: "May rent 26,000 — duplicate of payment 21027 on tenancy 901",
}
# Payment that exists ONLY on 894 → move to 901.
MOVE_PAYMENT = 20941  # Rs.20,000 booking advance, 2026-04-20

# rent_schedule rows on 894 that duplicate 901's Apr/May schedule → remove.
DUP_RENT_SCHEDULE = [15276, 15277]

# KYC fields present on tenant 897 but missing on tenant 914.
KYC_FIELDS = [
    "gender", "date_of_birth", "permanent_address", "email", "occupation",
    "father_name", "father_phone", "emergency_contact_name",
    "emergency_contact_phone", "emergency_contact_relationship",
    "id_proof_type", "id_proof_number", "food_preference",
    "educational_qualification", "office_address", "office_phone",
]

ORPHAN_TENANT_615 = 1169


def log(msg: str) -> None:
    print(msg)


async def audit(session, *, entity_type, entity_id, entity_name, field,
                old_value, new_value, note, room_number):
    await session.execute(text("""
        INSERT INTO audit_log (created_at, changed_by, entity_type, entity_id,
                               entity_name, field, old_value, new_value,
                               room_number, source, note, org_id)
        VALUES (now(), 'Kiran', :et, :eid, :en, :f, :ov, :nv, :rn, 'script', :note, 1)
    """), {"et": entity_type, "eid": entity_id, "en": entity_name, "f": field,
           "ov": old_value, "nv": new_value, "rn": room_number, "note": note})


async def main(write: bool) -> None:
    init_engine(os.getenv("DATABASE_URL"))
    async with get_session() as s:
        # Apr/May 2026 payments sit behind the frozen-period trigger. This merge
        # is a deliberate historical correction, so lift the guard for this txn only.
        if write:
            await s.execute(text("SET LOCAL app.allow_historical_write = 'true'"))

        # ── 1. Move the unique booking advance to the surviving tenancy ──────
        row = (await s.execute(text(
            "SELECT amount, notes FROM payments WHERE id = :i"), {"i": MOVE_PAYMENT})).first()
        log(f"MOVE  payment {MOVE_PAYMENT} Rs.{row[0]} ({row[1]}) : tenancy {DUP_TENANCY} -> {KEEP_TENANCY}")
        if write:
            await s.execute(text("UPDATE payments SET tenancy_id = :k WHERE id = :i"),
                            {"k": KEEP_TENANCY, "i": MOVE_PAYMENT})
            await audit(s, entity_type="payment", entity_id=MOVE_PAYMENT,
                        entity_name="T.Rakesh Chetan", field="payment.tenancy_id",
                        old_value=str(DUP_TENANCY), new_value=str(KEEP_TENANCY),
                        room_number="415",
                        note="Duplicate tenant merge 897->914: booking advance moved to surviving tenancy")

        # ── 2. Void the duplicated payments ──────────────────────────────────
        for pid, why in DUP_PAYMENTS.items():
            log(f"VOID  payment {pid} — {why}")
            if write:
                await s.execute(text("""
                    UPDATE payments
                       SET is_void = true,
                           notes = coalesce(notes,'') || ' | VOID: duplicate of tenancy 901 (tenant merge)'
                     WHERE id = :i
                """), {"i": pid})
                await audit(s, entity_type="payment", entity_id=pid,
                            entity_name="Rakesh Thallapally", field="payment.void",
                            old_value="false", new_value="true", room_number="415",
                            note=f"Duplicate tenant merge 897->914: {why}")

        # ── 3. Duplicate rent_schedule rows ──────────────────────────────────
        for rs_id in DUP_RENT_SCHEDULE:
            log(f"DROP  rent_schedule {rs_id} on tenancy {DUP_TENANCY} (duplicate of 901)")
            if write:
                await s.execute(text("DELETE FROM rent_schedule WHERE id = :i"), {"i": rs_id})

        # ── 4. Documents + onboarding session → surviving tenant/tenancy ─────
        for table in ("documents", "onboarding_sessions"):
            ids = (await s.execute(text(
                f"SELECT id FROM {table} WHERE tenancy_id = :d"), {"d": DUP_TENANCY})).scalars().all()
            if not ids:
                continue
            log(f"MOVE  {table} {ids} : tenant {DUP_TENANT}/tenancy {DUP_TENANCY} -> {KEEP_TENANT}/{KEEP_TENANCY}")
            if write:
                await s.execute(text(f"""
                    UPDATE {table} SET tenant_id = :kt, tenancy_id = :kc
                     WHERE tenancy_id = :d
                """), {"kt": KEEP_TENANT, "kc": KEEP_TENANCY, "d": DUP_TENANCY})

        # ── 5. Copy KYC fields onto the surviving tenant where blank ─────────
        cols = ", ".join(KYC_FIELDS)
        dup = (await s.execute(text(f"SELECT {cols} FROM tenants WHERE id = :i"),
                               {"i": DUP_TENANT})).mappings().first()
        keep = (await s.execute(text(f"SELECT {cols} FROM tenants WHERE id = :i"),
                                {"i": KEEP_TENANT})).mappings().first()
        fill = {f: dup[f] for f in KYC_FIELDS if keep[f] in (None, "") and dup[f] not in (None, "")}
        if fill:
            log(f"FILL  tenant {KEEP_TENANT} from {DUP_TENANT}: {list(fill)}")
            if write:
                sets = ", ".join(f"{f} = :{f}" for f in fill)
                await s.execute(text(f"UPDATE tenants SET {sets} WHERE id = :i"),
                                {**fill, "i": KEEP_TENANT})
                await audit(s, entity_type="tenant", entity_id=KEEP_TENANT,
                            entity_name="T.Rakesh Chetan", field="tenant.kyc_merge",
                            old_value=None, new_value=",".join(fill), room_number="415",
                            note=f"KYC copied from duplicate tenant {DUP_TENANT} (Rakesh Thallapally)")

        # ── 6. Retire the duplicate tenancy + tenant ─────────────────────────
        log(f"CANCEL tenancy {DUP_TENANCY} (status exited -> cancelled; hidden from search/reports)")
        log(f"RENAME tenant {DUP_TENANT} -> 'Rakesh Thallapally [merged into 914]'")
        if write:
            await s.execute(text(
                "UPDATE tenancies SET status = 'cancelled', updated_at = now() WHERE id = :i"),
                {"i": DUP_TENANCY})
            await s.execute(text(
                "UPDATE tenants SET name = 'Rakesh Thallapally [merged into 914]' WHERE id = :i"),
                {"i": DUP_TENANT})
            await audit(s, entity_type="tenancy", entity_id=DUP_TENANCY,
                        entity_name="Rakesh Thallapally", field="tenancy.status",
                        old_value="exited", new_value="cancelled", room_number="415",
                        note="Duplicate of tenancy 901 (same person, same phone) — merged, retired")

        # ── 7. Room 615 orphan tenant row ────────────────────────────────────
        orphan = (await s.execute(text(
            "SELECT name, phone FROM tenants WHERE id = :i"), {"i": ORPHAN_TENANT_615})).first()
        if orphan:
            log(f"DELETE tenant {ORPHAN_TENANT_615} '{orphan[0]}' ({orphan[1]}) — orphan, no tenancy/payments/docs")
            if write:
                await s.execute(text("DELETE FROM tenants WHERE id = :i"), {"i": ORPHAN_TENANT_615})
                await audit(s, entity_type="tenant", entity_id=ORPHAN_TENANT_615,
                            entity_name=orphan[0], field="tenant.delete",
                            old_value=orphan[1], new_value=None, room_number="615",
                            note="Orphan tenant row from booking; tenancy 1316 belongs to tenant 1175")

        if write:
            await s.commit()
            log("\nCOMMITTED")
        else:
            log("\nDRY RUN — nothing written. Re-run with --write")


if __name__ == "__main__":
    asyncio.run(main("--write" in sys.argv))
