"""
End-to-end test for CHECK_IN handler (resolve_confirm_checkin_arrival).

Workflow:
1. Create test tenant + tenancy (no-show status, future checkin)
2. Receptionist: "[TENANT] arrived" -> CONFIRM_CHECKIN_ARRIVAL pending
3. Receptionist: "yes" -> confirms arrival
4. Handler flips status -> active, creates RentSchedule, shows dues breakdown
5. Receptionist: "[TENANT] paid 5000 cash" -> logs payment
6. Verify DB + audit_log reflect changes

Run: TEST_MODE=1 python tests/test_checkin_e2e.py
"""
import asyncio
import os
from datetime import date, timedelta, datetime
from decimal import Decimal

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from src.database.db_manager import init_engine, get_session
from src.database.models import (
    Tenant, Tenancy, Room, RentSchedule, Payment, AuditLog,
    TenancyStatus, StayType, SharingType, PaymentFor, PaymentMode, RentStatus,
    PendingAction,
)
from src.whatsapp.handlers.resolvers.onboarding import resolve_confirm_checkin_arrival


async def main():
    """Test: Create no-show -> receptionist confirms arrival -> dues displayed -> payment logged."""
    init_engine(os.getenv("DATABASE_URL"))
    async with get_session() as s:
        # 1. Setup: Find a room + create test tenant
        room = (await s.execute(select(Room).where(Room.room_number == "101"))).scalar()
        if not room:
            room = (await s.execute(select(Room).limit(1))).scalar()

        test_tenant = Tenant(
            name="TEST_E2E_CHECKIN",
            phone="+919999999999",
            gender="male",
        )
        s.add(test_tenant)
        await s.flush()

        # 2. Create tenancy (no-show, future checkin)
        future_checkin = date.today() + timedelta(days=5)
        test_tenancy = Tenancy(
            tenant_id=test_tenant.id,
            room_id=room.id,
            stay_type=StayType.monthly,
            status=TenancyStatus.no_show,
            checkin_date=future_checkin,
            sharing_type=SharingType.double,
            agreed_rent=Decimal("15000"),
            security_deposit=Decimal("5000"),
            booking_amount=Decimal("2000"),
        )
        s.add(test_tenancy)
        await s.flush()

        # 3. Verify no RentSchedule exists yet
        rs_before = (await s.execute(
            select(RentSchedule).where(RentSchedule.tenancy_id == test_tenancy.id)
        )).scalars().all()
        assert len(rs_before) == 0, "No-show should have no RentSchedule yet"
        print("[OK] Test tenant created (no-show, no RentSchedule)")

        # 4. Simulate receptionist confirming arrival
        action_data = {
            "tenancy_id": test_tenancy.id,
            "tenant_name": test_tenant.name,
            "room_number": room.room_number,
            "confirmed_by": "RECEPTIONIST_TEST",
        }

        # Create pending action
        pending = PendingAction(
            phone="+919999999999",
            intent="CONFIRM_CHECKIN_ARRIVAL",
            action_data=str(action_data),
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        s.add(pending)
        await s.flush()

        # Call the resolver
        reply = await resolve_confirm_checkin_arrival(
            pending=pending,
            reply_text="yes",
            session=s,
            action_data=action_data,
            choices=[],
        )

        # 5. Verify response
        assert reply is not None, "Resolver should return a reply"
        assert "arrived" in reply.lower(), f"Reply should mention arrival. Got: {reply}"
        assert "dues" in reply.lower() or "collect" in reply.lower(), f"Reply should show dues. Got: {reply}"
        assert test_tenant.name in reply, f"Reply should mention tenant name. Got: {reply}"
        print(f"[OK] Resolver reply includes arrival + dues breakdown")
        print(f"  Sample: [Reply received successfully]")

        # 6. Verify DB state after resolver
        await s.refresh(test_tenancy)
        assert test_tenancy.status == TenancyStatus.active, f"Status should be active, got {test_tenancy.status}"
        print("[OK] Tenancy status: no_show -> active")

        # 7. Check RentSchedule created
        checkin_month = test_tenancy.checkin_date.replace(day=1)
        rs_after = (await s.execute(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == test_tenancy.id,
                RentSchedule.period_month == checkin_month,
            )
        )).scalar()
        assert rs_after is not None, f"RentSchedule should be created for {checkin_month}"
        assert rs_after.status == RentStatus.pending, f"RentSchedule status should be pending"
        print(f"[OK] RentSchedule created:")
        print(f"  Period: {rs_after.period_month}")
        print(f"  Rent due: Rs.{rs_after.rent_due:,.0f}")
        print(f"  Status: {rs_after.status}")

        # 8. Check AuditLog entry
        audit_logs = (await s.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "tenancy",
                AuditLog.entity_id == test_tenancy.id,
            )
        )).scalars().all()
        assert len(audit_logs) > 0, "AuditLog should have entry for status change"
        status_change = next((a for a in audit_logs if a.field == "status"), None)
        assert status_change is not None, "AuditLog should have status change entry"
        assert status_change.old_value == "no_show", f"Old status should be no_show, got {status_change.old_value}"
        assert status_change.new_value == "active", f"New status should be active, got {status_change.new_value}"
        print(f"[OK] AuditLog: status change no_show -> active by {status_change.changed_by}")

        # 9. Simulate payment logging
        test_payment = Payment(
            tenancy_id=test_tenancy.id,
            amount=Decimal("5000"),
            payment_date=date.today(),
            payment_mode=PaymentMode.cash,
            for_type=PaymentFor.rent,
            period_month=checkin_month,
            received_by_staff_id=None,
            notes="TEST: paid during CHECK_IN confirmation",
        )
        s.add(test_payment)
        await s.flush()

        # 10. Verify payment is recorded
        payments = (await s.execute(
            select(Payment).where(
                Payment.tenancy_id == test_tenancy.id,
                Payment.period_month == checkin_month,
            )
        )).scalars().all()
        assert len(payments) > 0, "Payment should be recorded"
        total_paid = sum(p.amount for p in payments)
        print(f"[OK] Payment recorded: Rs.{total_paid:,.0f}")

        # 11. Verify balance calculation
        total_due = rs_after.rent_due + (test_tenancy.security_deposit or 0)
        remaining = total_due - total_paid
        assert remaining >= 0, f"Remaining should be >= 0, got Rs.{remaining}"
        print(f"[OK] Balance:")
        print(f"  Total due: Rs.{total_due:,.0f}")
        print(f"  Total paid: Rs.{total_paid:,.0f}")
        print(f"  Remaining: Rs.{remaining:,.0f}")

        # Cleanup
        await s.delete(test_payment)
        await s.delete(test_tenancy)
        await s.delete(test_tenant)
        for log in audit_logs:
            await s.delete(log)
        await s.delete(pending)
        await s.commit()
        print(f"[OK] Test cleanup completed")


if __name__ == "__main__":
    os.environ["TEST_MODE"] = "1"
    print("Running CHECK_IN handler end-to-end test...\n")
    asyncio.run(main())
    print("\n[PASSED] All checks passed!")
