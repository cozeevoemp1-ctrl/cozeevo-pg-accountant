"""Tests for _build_daywise_row — verifies MONTHLY_HEADERS mapping for day-wise stays."""


def test_add_daywise_stay_builds_correct_row():
    """_build_daywise_row kwargs map correctly to MONTHLY_HEADERS positions."""
    from src.integrations.gsheets import MONTHLY_HEADERS, _build_daywise_row
    row = _build_daywise_row(
        room_number="305", tenant_name="Ramu", phone="9876543210",
        building="THOR", sharing="2-sharing", daily_rate=500.0,
        num_days=3, booking_amount=200.0, total_paid=1500.0,
        maintenance=0.0, checkin="01/04/2026", checkout="04/04/2026",
        status="ACTIVE", notes="", entered_by="onboarding_form",
    )
    h = {v: i for i, v in enumerate(MONTHLY_HEADERS)}
    assert row[h["Room"]] == "305"
    assert row[h["Name"]] == "Ramu"
    assert row[h["Rent"]] == 500.0          # daily rate
    assert row[h["Rent Due"]] == 1500.0     # 500 * 3 + 0 maintenance
    assert row[h["Total Paid"]] == 1500.0
    assert row[h["Balance"]] == 0.0
    assert row[h["Status"]] == "ACTIVE"
