"""Test the image-based check-in flow — edge cases and handlers."""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(override=True)


async def test():
    from src.database.db_manager import init_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL", "")
    engine = init_engine(db_url)
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with sf() as session:
        from src.database.models import (
            Room, Tenant, Tenancy, TenancyStatus, PendingAction, DocumentType,
        )
        from sqlalchemy import select
        from src.whatsapp.form_extractor import format_extracted_data
        from src.whatsapp.handlers.owner_handler import resolve_pending_action

        passed = 0
        failed = 0

        test_data = {
            "name": "Test User", "phone": "9876543210", "room_number": "G17",
            "monthly_rent": "22000", "rent_remarks": "21000 for first 2 months",
            "deposit": "22000", "deposit_remarks": "18000 refund on exit",
            "maintenance": "5000", "maintenance_remarks": "no damage",
            "date_of_admission": "01/04/2026", "gender": "male",
            "father_name": "Test Father", "email": "test@test.com",
            "educational_qualification": "B.Tech", "office_address": "Test Office",
            "occupation": "Engineer", "id_proof_type": "aadhar",
        }

        def check(name, condition, detail=""):
            nonlocal passed, failed
            if condition:
                print(f"  PASS: {name}")
                passed += 1
            else:
                print(f"  FAIL: {name} {detail}")
                failed += 1

        # --- Format tests ---
        print("\n== Format Tests ==")
        fmt = format_extracted_data(test_data, "haiku")
        check("shows rent remarks", "Rent terms" in fmt)
        check("shows deposit remarks", "Deposit terms" in fmt)
        check("shows maint remarks", "Maint. terms" in fmt)
        check("shows education", "Education" in fmt)
        check("shows office address", "Office Address" in fmt)
        check("shows occupation", "Occupation" in fmt)

        # --- Document types ---
        print("\n== Document Types ==")
        check("reg_form enum", DocumentType.reg_form.value == "reg_form")
        check("rules_page enum", DocumentType.rules_page.value == "rules_page")
        check("id_proof enum", DocumentType.id_proof.value == "id_proof")

        # --- Tenant model ---
        print("\n== Tenant Model ==")
        t = Tenant(name="test", phone="0000000000")
        t.educational_qualification = "B.Tech"
        t.office_address = "Addr"
        t.office_phone = "1234567890"
        check("educational_qualification", t.educational_qualification == "B.Tech")
        check("office_address", t.office_address == "Addr")
        check("office_phone", t.office_phone == "1234567890")

        # --- GSheets signature ---
        print("\n== GSheets Signature ==")
        import inspect
        from src.integrations.gsheets import add_tenant
        sig = inspect.signature(add_tenant)
        kyc_params = ["dob", "father_name", "father_phone", "address", "email",
                       "occupation", "education", "office_address", "office_phone",
                       "id_type", "id_number", "food_pref"]
        for p in kyc_params:
            check(f"param {p}", p in sig.parameters)

        # --- Edit flow ---
        print("\n== Edit Flow ==")

        def make_pa(step_data):
            return PendingAction(
                phone="7845952289", intent="FORM_EXTRACT_CONFIRM",
                action_data=json.dumps(step_data),
                choices="[]",
                expires_at=datetime.utcnow() + timedelta(minutes=30),
            )

        # Edit name
        r = await resolve_pending_action(
            make_pa({"step": "confirm_extracted", "extracted": dict(test_data), "provider": "haiku"}),
            "edit name Kanchan Sharma", session,
        )
        check("edit name", "Kanchan Sharma" in (r or ""))

        # Edit rent_terms
        r = await resolve_pending_action(
            make_pa({"step": "confirm_extracted", "extracted": dict(test_data), "provider": "haiku"}),
            "edit rent_terms first month 21k", session,
        )
        check("edit rent_terms", "first month 21k" in (r or ""))

        # Edit education
        r = await resolve_pending_action(
            make_pa({"step": "confirm_extracted", "extracted": dict(test_data), "provider": "haiku"}),
            "edit education MBA", session,
        )
        check("edit education", "MBA" in (r or ""))

        # Edit unknown field
        r = await resolve_pending_action(
            make_pa({"step": "confirm_extracted", "extracted": dict(test_data), "provider": "haiku"}),
            "edit blahblah value", session,
        )
        check("unknown field error", "Unknown field" in (r or ""))

        # Cancel
        r = await resolve_pending_action(
            make_pa({"step": "confirm_extracted", "extracted": dict(test_data), "provider": "haiku"}),
            "no", session,
        )
        check("cancel", "Cancelled" in (r or ""))

        # --- Room full flow ---
        print("\n== Room Full Flow ==")

        # Edit room when full
        r = await resolve_pending_action(
            make_pa({
                "step": "resolve_room_full", "extracted": dict(test_data),
                "room_number": "G17", "occupant_tenancies": [],
            }),
            "edit room T-201", session,
        )
        check("room full → edit room", "T-201" in (r or ""))

        # Invalid input when full
        r = await resolve_pending_action(
            make_pa({
                "step": "resolve_room_full", "extracted": dict(test_data),
                "room_number": "G17", "occupant_tenancies": [],
            }),
            "blah blah", session,
        )
        check("room full invalid", "KEEP_PENDING" in (r or ""))

        # --- Gender mismatch flow ---
        print("\n== Gender Mismatch Flow ==")

        # Proceed anyway
        r = await resolve_pending_action(
            make_pa({
                "step": "confirm_gender_mismatch", "extracted": dict(test_data),
                "room_type": "double", "max_occupancy": 2,
                "room_id": 1, "room_number": "G17",
            }),
            "yes", session,
        )
        check("gender mismatch → proceed", r is not None and "KEEP_PENDING" not in (r or "rejected"))

        # Edit room
        r = await resolve_pending_action(
            make_pa({
                "step": "confirm_gender_mismatch", "extracted": dict(test_data),
                "room_type": "double",
            }),
            "edit room T-301", session,
        )
        check("gender mismatch → edit room", "T-301" in (r or ""))

        # --- Sharing type flow ---
        print("\n== Sharing Type Flow ==")

        # Invalid choice
        r = await resolve_pending_action(
            make_pa({"step": "confirm_sharing", "room_type": "double", "extracted": dict(test_data)}),
            "blah", session,
        )
        check("sharing invalid", "KEEP_PENDING" in (r or ""))

        # --- COLLECT_DOCS flow ---
        print("\n== COLLECT_DOCS Flow ==")

        doc_pa = PendingAction(
            phone="7845952289", intent="COLLECT_DOCS",
            action_data=json.dumps({
                "step": "collecting", "tenant_name": "Test User",
                "room_number": "G17", "docs_saved": 1,
            }),
            choices="[]",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )

        # Text without image
        r = await resolve_pending_action(doc_pa, "hello", session)
        check("docs: text reminder", "Send photos" in (r or ""))

        # Done
        doc_pa2 = PendingAction(
            phone="7845952289", intent="COLLECT_DOCS",
            action_data=json.dumps({
                "step": "collecting", "tenant_name": "Test User",
                "room_number": "G17", "docs_saved": 3,
            }),
            choices="[]",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        r = await resolve_pending_action(doc_pa2, "done", session)
        check("docs: done", "Documents saved" in (r or "") and "3" in (r or ""))

        # Skip
        doc_pa3 = PendingAction(
            phone="7845952289", intent="COLLECT_DOCS",
            action_data=json.dumps({
                "step": "collecting", "tenant_name": "Test User",
                "room_number": "G17", "docs_saved": 0,
            }),
            choices="[]",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        r = await resolve_pending_action(doc_pa3, "skip", session)
        check("docs: skip", "Documents saved" in (r or ""))

        # Cancel
        doc_pa4 = PendingAction(
            phone="7845952289", intent="COLLECT_DOCS",
            action_data=json.dumps({
                "step": "collecting", "tenant_name": "Test User",
                "room_number": "G17", "docs_saved": 0,
            }),
            choices="[]",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        r = await resolve_pending_action(doc_pa4, "cancel", session)
        check("docs: cancel", "cancelled" in (r or "").lower())

        # ── Multi-turn correction test (field revert regression) ─────────
        # This tests the Lokesh bug: room 906→206 must NOT revert when phone is corrected next.
        print("\n== Multi-turn correction (field revert regression) ==")

        # Check-in form multi-turn: edit name then edit phone — both must hold
        checkin_pa = PendingAction(
            phone="7845952289", intent="FORM_EXTRACT_CONFIRM",
            action_data=json.dumps({
                "step": "confirm_extracted",
                "extracted": {"name": "WrongName", "phone": "0000000000", "room_number": "G17", "monthly_rent": "22000"},
                "provider": "haiku",
            }),
            choices="[]",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        # Turn 1: correct name
        r1 = await resolve_pending_action(checkin_pa, "edit name Soumya Devi", session)
        check("checkin edit name: accepted", "Soumya Devi" in (r1 or ""))
        # Turn 2: correct phone — using the SAME pending object (which was updated in-place)
        import json as _json
        ad2 = _json.loads(checkin_pa.action_data)
        check("checkin edit name: persisted in pending", ad2.get("extracted", {}).get("name") == "Soumya Devi")
        await resolve_pending_action(checkin_pa, "edit phone 9876543210", session)
        ad3 = _json.loads(checkin_pa.action_data)
        check("checkin multi-edit: name held after phone edit", ad3.get("extracted", {}).get("name") == "Soumya Devi")
        check("checkin multi-edit: phone updated", ad3.get("extracted", {}).get("phone") == "9876543210")

        # ── Checkout form OCR test (CHECKOUT_FORM_CONFIRM) ────────────────
        print("\n== Checkout Form OCR Flow ==")

        checkout_extracted = {
            "name": "Soumya", "room_number": "906", "phone": "1111111111",
            "checkout_date": "26/04/2026", "security_deposit": "20000",
        }
        co_pa = PendingAction(
            phone="7845952289", intent="CHECKOUT_FORM_CONFIRM",
            action_data=json.dumps({
                "step": "confirm_checkout_extracted",
                "extracted": dict(checkout_extracted),
            }),
            choices="[]",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )

        # Test: edit room 206
        r = await resolve_pending_action(co_pa, "edit room 206", session)
        check("checkout edit room: accepted", "__KEEP_PENDING__" in (r or "") and "206" in (r or ""))
        ad = _json.loads(co_pa.action_data)
        check("checkout edit room: persisted in pending", ad.get("extracted", {}).get("room_number") == "206")

        # Test: edit phone — room must NOT revert to 906
        r = await resolve_pending_action(co_pa, "edit phone 9876543210", session)
        ad2 = _json.loads(co_pa.action_data)
        check("checkout multi-edit: room held (no revert)", ad2.get("extracted", {}).get("room_number") == "206")
        check("checkout multi-edit: phone updated", ad2.get("extracted", {}).get("phone") == "9876543210")

        # Test: edit unknown field
        co_pa2 = PendingAction(
            phone="7845952289", intent="CHECKOUT_FORM_CONFIRM",
            action_data=json.dumps({"step": "confirm_checkout_extracted", "extracted": dict(checkout_extracted)}),
            choices="[]",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        r = await resolve_pending_action(co_pa2, "edit nonexistentfield blah", session)
        check("checkout edit unknown field: error", "Unknown field" in (r or "") or "Valid" in (r or ""))

        # Test: cancel
        co_pa3 = PendingAction(
            phone="7845952289", intent="CHECKOUT_FORM_CONFIRM",
            action_data=json.dumps({"step": "confirm_checkout_extracted", "extracted": dict(checkout_extracted)}),
            choices="[]",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        r = await resolve_pending_action(co_pa3, "cancel", session)
        check("checkout cancel", "cancelled" in (r or "").lower())

        print(f"\n{'='*40}")
        print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
        if failed:
            print("SOME TESTS FAILED")
            sys.exit(1)
        else:
            print("ALL TESTS PASSED")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test())
