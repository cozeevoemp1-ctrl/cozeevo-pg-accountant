#!/usr/bin/env python3
"""
Find and cancel duplicate active tenancies for the same tenant in the same room.
Keeps the earlier one (by checkin_date), cancels the later one.
"""
import os
from datetime import datetime
from dotenv import load_dotenv
from src.database.models import Tenancy, TenancyStatus, AuditLog
from sqlalchemy import create_engine, select, func, and_
from sqlalchemy.orm import Session

def main():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set in .env")
        return

    engine = create_engine(db_url, echo=False)
    session = Session(engine)

    # Find all (tenant_id, room_id) pairs with multiple active tenancies
    duplicates = (
        session.execute(
            select(
                Tenancy.tenant_id,
                Tenancy.room_id,
                func.count(Tenancy.id).label("count")
            )
            .where(Tenancy.status == TenancyStatus.active)
            .group_by(Tenancy.tenant_id, Tenancy.room_id)
            .having(func.count(Tenancy.id) > 1)
        )
    ).all()

    if not duplicates:
        print("✓ No duplicate active tenancies found.")
        session.close()
        return

    print(f"Found {len(duplicates)} duplicate (tenant, room) pairs:\n")

    for tenant_id, room_id, count in duplicates:
        print(f"  Tenant {tenant_id}, Room {room_id}: {count} active tenancies")

        # Get all tenancies for this pair, ordered by checkin_date
        tenancies = (
            session.execute(
                select(Tenancy)
                .where(
                    and_(
                        Tenancy.tenant_id == tenant_id,
                        Tenancy.room_id == room_id,
                        Tenancy.status == TenancyStatus.active
                    )
                )
                .order_by(Tenancy.checkin_date.asc(), Tenancy.created_at.asc())
            )
        ).scalars().all()

        # Keep the first (earliest checkin), cancel the rest
        to_keep = tenancies[0]
        to_cancel = tenancies[1:]

        for tenancy in to_cancel:
            print(f"    → Cancelling tenancy {tenancy.id} (checkin {tenancy.checkin_date}, created {tenancy.created_at})")
            print(f"      Keeping tenancy {to_keep.id} (checkin {to_keep.checkin_date}, created {to_keep.created_at})")

            # Cancel it
            tenancy.status = TenancyStatus.cancelled

            # Log the action
            session.add(AuditLog(
                changed_by="auto_fix_duplicates.py",
                entity_type="tenancy",
                entity_id=tenancy.id,
                entity_name=f"Tenant {tenancy.tenant_id}, Room {tenancy.room_id}",
                field="status",
                old_value=TenancyStatus.active.value,
                new_value=TenancyStatus.cancelled.value,
                source="script",
                org_id=tenancy.org_id,
            ))

    # Commit all changes
    session.commit()
    print(f"\n✓ Fixed all duplicate tenancies.")
    session.close()

if __name__ == "__main__":
    main()
