"""
One-off: migrate room-000 no_show tenants → pending_review OnboardingSession records.

What it does (per tenant):
  1. Creates an OnboardingSession (status=pending_review) with all financial details
     from the existing tenancy, so admin can assign a real room via Bookings page.
  2. Voids the ₹2,000 advance payment on the old tenancy (approve flow re-creates it
     on the new tenancy when admin checks them in).
  3. Cancels the old room-000 tenancy.

Dry-run by default. Pass --write to apply.
"""
import asyncio, json, sys, uuid
from datetime import date

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text

URL = "postgresql+asyncpg://postgres:Anchorstrong123!@db.oxiqomoilqwfxjauxhzp.supabase.co:5432/postgres"
CREATED_BY = "+917845952289"  # Kiran


async def main(write: bool) -> None:
    engine = create_async_engine(URL)
    async with AsyncSession(engine) as s:
        rows = (await s.execute(text("""
            SELECT
                t.id           AS tenancy_id,
                tn.id          AS tenant_id,
                tn.name,
                tn.phone,
                t.checkin_date,
                t.agreed_rent,
                t.security_deposit,
                t.booking_amount,
                t.maintenance_fee,
                t.stay_type::text   AS stay_type,
                t.sharing_type::text AS sharing_type
            FROM tenancies t
            JOIN tenants  tn ON tn.id = t.tenant_id
            JOIN rooms    r  ON r.id  = t.room_id
            WHERE r.room_number = :room
              AND t.status::text  = :status
            ORDER BY t.id
        """), {"room": "000", "status": "no_show"})).mappings().all()

        if not rows:
            print("No room-000 no_show tenants found.")
            return

        print(f"Found {len(rows)} tenant(s) to migrate:\n")

        for r in rows:
            token = str(uuid.uuid4())
            tenant_data = json.dumps({"name": r["name"], "phone": r["phone"]})

            print(f"  {'[DRY RUN] ' if not write else ''}Migrating: {r['name']}")
            print(f"    tenancy_id={r['tenancy_id']}  tenant_id={r['tenant_id']}")
            print(f"    rent={r['agreed_rent']}  deposit={r['security_deposit']}"
                  f"  booking={r['booking_amount']}  maint={r['maintenance_fee']}")
            print(f"    checkin={r['checkin_date']}  stay={r['stay_type']}"
                  f"  sharing={r['sharing_type']}")
            print(f"    session token: {token}")

            if write:
                # 1. Create pending_review OnboardingSession
                await s.execute(text("""
                    INSERT INTO onboarding_sessions (
                        token, status, created_by_phone, tenant_phone,
                        room_id, agreed_rent, security_deposit, maintenance_fee,
                        booking_amount, sharing_type, checkin_date, stay_type,
                        tenant_id, tenant_data, signature_image,
                        created_at, completed, expires_at
                    ) VALUES (
                        :token, 'pending_review', :created_by, :phone,
                        NULL, :rent, :deposit, :maintenance,
                        :booking, :sharing, :checkin, :stay_type,
                        :tenant_id, :tenant_data, 'I_AGREE:migrated:auto',
                        NOW(), FALSE, '2099-12-31'
                    )
                """), {
                    "token":       token,
                    "created_by":  CREATED_BY,
                    "phone":       r["phone"],
                    "rent":        float(r["agreed_rent"]),
                    "deposit":     float(r["security_deposit"]),
                    "maintenance": float(r["maintenance_fee"]),
                    "booking":     float(r["booking_amount"]),
                    "sharing":     r["sharing_type"],
                    "checkin":     r["checkin_date"],
                    "stay_type":   r["stay_type"],
                    "tenant_id":   r["tenant_id"],
                    "tenant_data": tenant_data,
                })

                # 2. Void advance payments on old tenancy so approve doesn't double-count
                await s.execute(text("SET LOCAL app.allow_historical_write = 'true'"))
                voided = (await s.execute(text("""
                    UPDATE payments
                    SET is_void = TRUE
                    WHERE tenancy_id = :tid AND is_void = FALSE
                    RETURNING id, amount
                """), {"tid": r["tenancy_id"]})).all()
                for p in voided:
                    print(f"    voided payment id={p[0]} Rs{p[1]}")

                # 3. Cancel old room-000 tenancy
                await s.execute(text("""
                    UPDATE tenancies
                    SET status = 'cancelled', checkout_date = :today
                    WHERE id = :tid
                """), {"tid": r["tenancy_id"], "today": date.today()})

                print(f"    OK - old tenancy cancelled\n")
            else:
                print()

        if write:
            await s.commit()
            print("Migration complete. Open /onboarding/bookings to assign rooms.")
        else:
            print("Dry run complete. Re-run with --write to apply.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(write="--write" in sys.argv))
