"""One-off: export a REAL-data snapshot for the Web v2 Bed-Board demo artifact.

Reads the live DB (rooms/tenancies/payments/RS) as of today and writes a JSON
blob the demo HTML embeds (claude.ai artifact 6e816cd3). Room structure, staff
rooms, bed states, dues, register days, bookings/checkouts/notices and KPIs
all come from the DB — nothing invented. Uses services/dues.py + daily_dues
so the demo shows exactly what the app computes.

Run:  venv/Scripts/python scripts/_export_web_demo_data.py
Out:  scripts/_web_demo_data.json
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import and_, func, or_, select

from src.database.db_manager import get_session, init_engine
init_engine(os.environ["DATABASE_URL"])
from src.database.models import (
    OnboardingSession, Payment, PaymentFor, Property, RentSchedule, Room,
    SharingType, StayType, Tenancy, TenancyStatus, Tenant,
)
from src.services.daily_dues import daily_dues
from src.services.dues import monthly_dues
from src.services.occupancy import (
    get_occupied_beds, get_occupied_beds_asof, get_total_revenue_beds,
)
from src.services.reporting import collection_summary
from services.property_logic import is_deposit_eligible

TODAY = date.today()
PERIOD = TODAY.replace(day=1)
IST_OFFSET = timedelta(hours=5, minutes=30)


def inr(n) -> str:
    return f"₹{int(round(float(n or 0))):,}"


def dshort(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def dfull(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def dyr(d: date) -> str:
    return f"{d.day} {d.strftime('%b %y')}"


def fmt_phone(p: str | None) -> str:
    p = (p or "").lstrip("+")
    if p.startswith("91") and len(p) == 12:
        p = p[2:]
    return f"{p[:5]} {p[5:]}" if len(p) == 10 else p


async def main() -> None:
    async with get_session() as session:
        # ── rooms + properties ───────────────────────────────────────────────
        rooms_rows = (await session.execute(
            select(Room, Property.name.label("prop"))
            .join(Property, Property.id == Room.property_id)
            .where(Room.active == True, Room.room_number != "000")  # noqa: E712
            .order_by(Property.name, Room.floor, Room.room_number)
        )).all()

        # ── tenancies (active + no_show) with tenants ────────────────────────
        ten_rows = (await session.execute(
            select(Tenancy, Tenant, Room.room_number, Room.max_occupancy)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]))
        )).all()
        tenancy_ids = [t.Tenancy.id for t in ten_rows]

        # ── RS rows for this period ──────────────────────────────────────────
        rs_map = {
            r.tenancy_id: r for r in (await session.execute(
                select(RentSchedule).where(
                    RentSchedule.tenancy_id.in_(tenancy_ids),
                    RentSchedule.period_month == PERIOD,
                )
            )).scalars()
        }

        # ── payment aggregates per tenancy ───────────────────────────────────
        async def sums(where) -> dict[int, float]:
            rows = (await session.execute(
                select(Payment.tenancy_id, func.sum(Payment.amount))
                .where(Payment.tenancy_id.in_(tenancy_ids), Payment.is_void == False, where)  # noqa: E712
                .group_by(Payment.tenancy_id)
            )).all()
            return {r[0]: float(r[1] or 0) for r in rows}

        rent_paid = await sums(and_(Payment.for_type == PaymentFor.rent, Payment.period_month == PERIOD))
        dep_paid = await sums(Payment.for_type == PaymentFor.deposit)
        adv_paid = await sums(Payment.for_type == PaymentFor.booking)
        stay_paid = await sums(or_(Payment.for_type.is_(None),
                                   Payment.for_type.notin_([PaymentFor.booking, PaymentFor.deposit])))

        # last 3 ledger rows per tenancy
        led_rows = (await session.execute(
            select(Payment).where(Payment.tenancy_id.in_(tenancy_ids), Payment.is_void == False)  # noqa: E712
            .order_by(Payment.payment_date.desc(), Payment.id.desc())
        )).scalars().all()
        ledger: dict[int, list] = defaultdict(list)
        for p in led_rows:
            if len(ledger[p.tenancy_id]) < 3:
                mode = p.payment_mode.value if p.payment_mode else "?"
                ft = p.for_type.value if p.for_type else "rent"
                ledger[p.tenancy_id].append([dshort(p.payment_date), f"{mode} · {ft}", inr(p.amount)])

        # ── per-tenancy dues + status ────────────────────────────────────────
        occ_by_room: dict[str, list[dict]] = defaultdict(list)
        dues_total = 0.0
        dues_count = 0
        for row in ten_rows:
            tn, te, room_no, max_occ = row.Tenancy, row.Tenant, row.room_number, row.max_occupancy
            rs = rs_map.get(tn.id)
            is_daily = tn.stay_type == StayType.daily
            if tn.status == TenancyStatus.no_show:
                occ_by_room[room_no].append({
                    "kind": "hold", "tn": tn, "te": te, "dues": 0.0, "st": "vac",
                    "max_occ": max_occ,
                })
                continue
            if is_daily:
                owed, dues, _ = daily_dues(tn.checkin_date, tn.checkout_date, tn.agreed_rent, stay_paid.get(tn.id, 0))
                paid_any = stay_paid.get(tn.id, 0) > 0
                st = "paid" if dues <= 0 else ("part" if paid_any else "due")
                bd = None
            else:
                bd = monthly_dues(
                    period=PERIOD, as_of=TODAY,
                    checkin_date=tn.checkin_date,
                    agreed_rent=tn.agreed_rent,
                    security_deposit=tn.security_deposit,
                    rent_due=float(rs.rent_due) if rs else float(tn.agreed_rent or 0),
                    adjustment=float(rs.adjustment or 0) if rs else 0,
                    rent_paid=rent_paid.get(tn.id, 0),
                    deposit_paid=dep_paid.get(tn.id, 0),
                    booking_paid_rows=adv_paid.get(tn.id, 0),
                    booking_amount_field=tn.booking_amount,
                )
                dues = bd.total
                # Partial = paid something toward THIS period (rent); all-time
                # deposit history must not turn an unpaid month amber.
                paid_any = rent_paid.get(tn.id, 0) > 0
                st = "paid" if dues <= 0 else ("part" if paid_any else "due")
            if dues > 0:
                dues_total += dues
                dues_count += 1
            occ_by_room[room_no].append({
                "kind": "daily" if is_daily else "monthly", "tn": tn, "te": te,
                "dues": dues, "st": st, "bd": bd, "max_occ": max_occ,
            })

        # ── today's movements ────────────────────────────────────────────────
        today_rooms: set[str] = set()
        checkins_today = checkouts_today = 0
        refundable_today = 0.0
        for row in ten_rows:
            tn, room_no = row.Tenancy, row.room_number
            if tn.checkin_date == TODAY:
                today_rooms.add(room_no)
                checkins_today += 1
            if tn.status == TenancyStatus.active and (tn.expected_checkout == TODAY or tn.checkout_date == TODAY):
                today_rooms.add(room_no)
                checkouts_today += 1
                if tn.stay_type != StayType.daily and is_deposit_eligible(tn.notice_date):
                    refundable_today += max(0.0, float(tn.security_deposit or 0) - float(tn.maintenance_fee or 0))

        # ── board: floors + beds + detail ────────────────────────────────────
        floors_map: dict[tuple, list[str]] = {}
        rooms_json: dict[str, dict] = {}
        detail: dict[str, dict] = {}
        for r in rooms_rows:
            room, prop = r.Room, r.prop
            bldg = prop.split()[-1].upper()
            fl = "G" if (room.floor or 0) == 0 else str(room.floor)
            floors_map.setdefault((bldg, fl), []).append(room.room_number)

            occs = occ_by_room.get(room.room_number, [])
            real = [o for o in occs if o["kind"] in ("monthly", "daily")]
            holds = [o for o in occs if o["kind"] == "hold"]
            premium = any(o["tn"].sharing_type == SharingType.premium for o in real)
            if room.is_staff_room:
                beds = ["staff"] * (room.max_occupancy or 1)
            elif premium:
                # Whole-room tenant = ONE wide bed icon, no phantom vacant beds.
                beds = [o["st"] for o in real]
            else:
                beds = [o["st"] for o in real][: room.max_occupancy or 1]
                while len(beds) < (room.max_occupancy or 1):
                    beds.append("vac")
            rooms_json[room.room_number] = {
                "beds": beds,
                "premium": premium,
                "bed_count": room.max_occupancy or 1,
                "staff": bool(room.is_staff_room),
                "today": room.room_number in today_rooms,
            }

            # inspector detail
            rt = room.room_type.value if room.room_type else "room"
            rents = [float(o["tn"].agreed_rent or 0) for o in real if o["tn"].agreed_rent]
            rent_str = f" · {inr(rents[0])}" + ("/day" if any(o["kind"] == "daily" for o in real) else " per bed") if rents else ""
            meta = f"{bldg} · Floor {fl} · {rt.title()}{rent_str}"
            if room.is_staff_room:
                meta += " · STAFF ROOM"
            occupied_n = sum((room.max_occupancy or 1) if o["tn"].sharing_type == SharingType.premium else 1 for o in real)
            occ_line = ("staff room · not revenue" if room.is_staff_room
                        else f"{min(occupied_n, room.max_occupancy or 1)} of {room.max_occupancy or 1} beds occupied"
                        + (f" · {len(holds)} booking hold" if holds else ""))
            flag = None
            if holds:
                h = holds[0]
                adv = adv_paid.get(h["tn"].id, 0) or float(h["tn"].booking_amount or 0)
                flag = (f"Booking hold: {h['te'].name} — advance {inr(adv)} held, "
                        f"check-in {dfull(h['tn'].checkin_date) if h['tn'].checkin_date else 'TBD'}.")
            tenants_j = []
            for o in real:
                tn, te = o["tn"], o["te"]
                rows = []
                if o["kind"] == "daily":
                    nights = (tn.checkout_date - tn.checkin_date).days if tn.checkin_date and tn.checkout_date else 0
                    rows.append([f"Stay · {nights} nights × {inr(tn.agreed_rent)}", inr(nights * float(tn.agreed_rent or 0))])
                    if stay_paid.get(tn.id, 0):
                        rows.append(["Paid", inr(stay_paid[tn.id])])
                else:
                    bd = o["bd"]
                    rent_line = bd.prorated_rent if bd.is_first_month and bd.prorated_rent is not None else bd.effective_due
                    rows.append([f"Rent · {PERIOD.strftime('%B')}", inr(rent_line)])
                    if rent_paid.get(tn.id, 0):
                        rows.append([f"Paid · {PERIOD.strftime('%B')} rent", inr(rent_paid[tn.id])])
                    if bd.deposit_due > 0:
                        rows.append(["Security deposit due", inr(bd.deposit_due)])
                tenants_j.append({
                    "n": te.name, "ph": fmt_phone(te.phone),
                    "since": (f"in {dfull(tn.checkin_date)}" if tn.checkin_date else "")
                             + (" · premium" if tn.sharing_type == SharingType.premium else "")
                             + (" · day-stay" if o["kind"] == "daily" else ""),
                    "st": o["st"], "rows": rows,
                    "tot": ["Outstanding", inr(o["dues"]), o["dues"] <= 0],
                    "ledger": ledger.get(tn.id, []),
                    "cta": f"Collect {inr(o['dues'])}" if o["dues"] > 0 else None,
                })
            detail[room.room_number] = {"meta": meta, "occ": occ_line, "flag": flag, "tenants": tenants_j}

        floors = [[b, f, rs_] for (b, f), rs_ in floors_map.items()]

        # ── tenants table ────────────────────────────────────────────────────
        tenants_tab = []
        for row in ten_rows:
            tn, te, room_no = row.Tenancy, row.Tenant, row.room_number
            occs = [o for o in occ_by_room.get(room_no, []) if o["tn"].id == tn.id and o["kind"] != "hold"]
            if not occs:
                continue
            o = occs[0]
            st = ("day" if o["kind"] == "daily" else
                  "notice" if tn.notice_date else o["st"])
            tenants_tab.append([
                te.name, fmt_phone(te.phone), room_no, float(tn.agreed_rent or 0), st,
                dyr(tn.checkin_date) if tn.checkin_date else "", round(o["dues"]),
                float(tn.security_deposit or 0),
            ])
        tenants_tab.sort(key=lambda t: -t[6])
        n_day = sum(1 for t in tenants_tab if t[4] == "day")
        n_notice = sum(1 for t in tenants_tab if t[4] == "notice")

        # ── daily register (last 12 days) ────────────────────────────────────
        since = TODAY - timedelta(days=11)
        reg_rows = (await session.execute(
            select(Payment, Tenant.name, Room.room_number)
            .join(Tenancy, Tenancy.id == Payment.tenancy_id)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Payment.is_void == False, Payment.payment_date >= since)  # noqa: E712
            .order_by(Payment.payment_date.desc(), Payment.created_at.desc())
        )).all()
        type_map = {"rent": "rent", "maintenance": "rent", "deposit": "deposit", "booking": "advance", "other": "rent"}
        days: dict[str, dict] = {}
        for r in reg_rows:
            p = r.Payment
            iso = p.payment_date.isoformat()
            d = days.setdefault(iso, {"count": "no count logged", "entries": []})
            t = (p.created_at + IST_OFFSET).strftime("%H:%M") if p.created_at else "--:--"
            ft = p.for_type.value if p.for_type else "rent"
            mode = p.payment_mode.value if p.payment_mode else "upi"
            d["entries"].append([t, r.name, r.room_number, type_map.get(ft, "rent"), mode, int(float(p.amount)), "app"])
        try:
            from src.database.models import CashCount
            for c in (await session.execute(
                select(CashCount).where(CashCount.date >= since)
            )).scalars():
                iso = c.date.isoformat()
                if iso in days:
                    days[iso]["count"] = f"{inr(c.amount)} counted by {c.counted_by}"
        except Exception:
            pass

        # ── KPIs ─────────────────────────────────────────────────────────────
        total_beds = await get_total_revenue_beds(session)
        occupied = await get_occupied_beds(session, TODAY)
        cs = await collection_summary(period_month=PERIOD.strftime("%Y-%m"), session=session)
        month_received = float(await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.is_void == False,  # noqa: E712
                Payment.payment_date >= PERIOD, Payment.payment_date <= TODAY,
            )
        ) or 0)

        # ── occupancy history (last 6 months) ────────────────────────────────
        occ_months = []
        for i in range(5, -1, -1):
            y = PERIOD.year + (PERIOD.month - 1 - i) // 12
            m = (PERIOD.month - 1 - i) % 12 + 1
            probe = TODAY if (y, m) == (PERIOD.year, PERIOD.month) else (
                date(y + (1 if m == 12 else 0), m % 12 + 1, 1) - timedelta(days=1))
            n = await get_occupied_beds_asof(session, probe)
            occ_months.append([date(y, m, 1).strftime("%b"), round(n * 100 / total_beds, 1) if total_beds else 0])

        # ── bookings / checkouts / notices views ─────────────────────────────
        bookings = []
        obs_rows = (await session.execute(
            select(OnboardingSession).where(
                OnboardingSession.status.in_(["pending_tenant", "pending_review"]))
        )).scalars().all()
        obs_by_tenancy = {o.tenancy_id: o for o in obs_rows if o.tenancy_id}
        for row in ten_rows:
            tn, te, room_no = row.Tenancy, row.Tenant, row.room_number
            if tn.status != TenancyStatus.no_show:
                continue
            obs = obs_by_tenancy.get(tn.id)
            st = "paid" if (obs and obs.status == "pending_review") else "part"
            note = ("Form filled, ready" if st == "paid" else "Awaiting form")
            adv = adv_paid.get(tn.id, 0) or float(tn.booking_amount or 0)
            when = (f"in {dshort(tn.checkin_date)}" if tn.checkin_date and tn.checkin_date >= TODAY
                    else f"was {dshort(tn.checkin_date)}" if tn.checkin_date else "TBD")
            bookings.append([te.name, room_no, when, int(adv), note, st])
        bookings.sort(key=lambda b: b[2])

        checkouts = []
        notices = []
        for row in ten_rows:
            tn, te, room_no = row.Tenancy, row.Tenant, row.room_number
            if tn.status != TenancyStatus.active or not tn.notice_date:
                continue
            eligible = is_deposit_eligible(tn.notice_date)
            last = tn.expected_checkout
            when = "today" if last == TODAY else (dshort(last) if last else "TBD")
            o = next((x for x in occ_by_room.get(room_no, []) if x["tn"].id == tn.id), None)
            dues = round(o["dues"]) if o else 0
            notices.append([te.name, room_no, dshort(tn.notice_date), when,
                            "eligible" if eligible else "late · next cycle",
                            "deposit refundable" if eligible else "full month rent due"])
            if last and last >= TODAY:
                checkouts.append([te.name, room_no, when, float(tn.security_deposit or 0), dues,
                                  f"notice {dshort(tn.notice_date)} · " + ("eligible" if eligible else "late, next cycle")])
        checkouts.sort(key=lambda c: (c[2] != "today", c[2]))

    out = {
        "as_of": TODAY.isoformat(),
        "as_of_label": TODAY.strftime("%a ") + dfull(TODAY),
        "month": PERIOD.strftime("%B"),
        "mon_short": PERIOD.strftime("%b"),
        "kpis": {
            "occupied": occupied, "total_beds": total_beds,
            "vacant": max(0, total_beds - occupied),
            "occ_pct": round(occupied * 100 / total_beds, 1) if total_beds else 0,
            "dues_total": round(dues_total), "dues_count": dues_count,
            "collected": cs.collected, "expected": cs.expected, "collect_pct": cs.collection_pct,
            "month_received": round(month_received),
            "checkins_today": checkins_today, "checkouts_today": checkouts_today,
            "refundable_today": round(refundable_today),
            "active_tenants": len([1 for r in ten_rows if r.Tenancy.status == TenancyStatus.active]),
            "day_stay": n_day, "on_notice": n_notice,
        },
        "floors": floors,
        "rooms": rooms_json,
        "detail": detail,
        "tenants": tenants_tab,
        "days": days,
        "bookings": bookings,
        "checkouts": checkouts,
        "notices": notices,
        "occ_months": occ_months,
    }
    dest = Path(__file__).parent / "_web_demo_data.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {dest} — {len(rooms_json)} rooms, {len(tenants_tab)} tenants, "
          f"{len(days)} register days, occupied {occupied}/{total_beds}")


if __name__ == "__main__":
    asyncio.run(main())
