"""
September-2026 reconciliation — backup Google Sheet vs the app (DB).

Source sheet: "September Month Collection" (env SOURCE_SHEET_ID), tabs
  'September Long Term'  monthly tenants, Sep cols: Sep / Sep Cash / Sep UPI /
                         Paid Date / Sep Balance, plus Checkin/out + vacation
  'Day wise'             short stays
DB: tenancies + rent_schedule + payments (monthly), daywise_stays (short stays)

Read-only. Reports differences; writes nothing to DB or Sheet.
Matching helpers are imported from the August reconcilers — never re-implemented.

Run: venv/Scripts/python scripts/_reconcile_sept_sheet.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from sqlalchemy import text

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from _reconcile_aug_cash import money, norm_name, norm_room, room_key, similar  # noqa: E402
from _reconcile_aug_upi import phone10  # noqa: E402
from src.database.db_manager import get_session, init_engine  # noqa: E402

SOURCE_SHEET_ID = os.getenv("SOURCE_SHEET_ID", "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0")
CREDS = "credentials/gsheets_service_account.json"
PERIOD = date(2026, 9, 1)
SEP_FROM, SEP_TO = date(2026, 9, 1), date(2026, 9, 30)


def parse_date(v):
    s = str(v or "").strip()
    if not s:
        return None
    for f in ("%d/%m/%Y", "%d-%m-%Y", "%d-%m-%y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def open_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDS, scopes=scopes)
    return gspread.authorize(creds).open_by_key(SOURCE_SHEET_ID)


def _reader(rows):
    hdr = [h.strip() for h in rows[0]]
    C = {h: i for i, h in enumerate(hdr)}

    def cell(r, name):
        i = C.get(name)
        return r[i] if i is not None and i < len(r) else ""

    return cell


def read_long_term(sh):
    rows = sh.worksheet("September Long Term").get_all_values()
    cell = _reader(rows)
    out = []
    for r in rows[1:]:
        name = cell(r, "Name").strip()
        if not name:
            continue
        out.append({
            "room": norm_room(cell(r, "Room No")),
            "name": norm_name(name),
            "raw_name": name,
            "phone": phone10(cell(r, "Mobile Number")),
            "checkin": parse_date(cell(r, "Checkin Date")),
            "status": cell(r, "Checkin/out").strip().upper(),
            "rent": money(cell(r, "Monthly Rent")),
            "sep_state": cell(r, "Sep").strip(),
            "sep_cash": money(cell(r, "Sep Cash")),
            "sep_upi": money(cell(r, "Sep UPI")),
            "sep_balance": cell(r, "Sep Balance").strip(),
            "vacation": cell(r, "vacation").strip(),
            "comments": cell(r, "Comments").strip(),
        })
    return out


def read_daywise(sh):
    rows = sh.worksheet("Day wise").get_all_values()
    cell = _reader(rows)
    out = []
    for r in rows[1:]:
        name = cell(r, "Name").strip()
        ci = parse_date(cell(r, "Checkin date"))
        if not name or not ci:
            continue
        if not (SEP_FROM <= ci <= SEP_TO):
            continue
        out.append({
            "room": norm_room(cell(r, "Room No")),
            "name": norm_name(name),
            "raw_name": name,
            "phone": phone10(cell(r, "Mobile Number")),
            "checkin": ci,
            "checkout": parse_date(cell(r, "Checkout date")),
            "days": cell(r, "No.Of.days").strip(),
            "total": money(cell(r, "Total Rent")),
            "booking": money(cell(r, "Booking amount")),
            "paid_so_far": money(cell(r, "Paid so far")),
            "dues": money(cell(r, "Total dues")),
            "status": cell(r, "Status").strip().upper(),
        })
    return out


async def load_db():
    init_engine(os.environ["DATABASE_URL"])
    async with get_session() as s:
        tenancies = (await s.execute(text("""
            SELECT tc.id, r.room_number, t.name, t.phone,
                   tc.status::text AS status, tc.stay_type::text AS stay_type,
                   tc.checkin_date, tc.checkout_date, tc.agreed_rent,
                   COALESCE(rs.rent_due,0) + COALESCE(rs.adjustment,0) AS due
            FROM tenancies tc
            JOIN tenants t ON t.id = tc.tenant_id
            LEFT JOIN rooms r ON r.id = tc.room_id
            LEFT JOIN rent_schedule rs
                   ON rs.tenancy_id = tc.id AND rs.period_month = :pm
            WHERE tc.checkin_date < DATE '2026-10-01'
              AND (tc.checkout_date IS NULL OR tc.checkout_date >= :pm)
        """), {"pm": PERIOD})).mappings().all()

        # payments RECEIVED in September (cash-flow view -> matches the sheet's
        # 'Sep Cash'/'Sep UPI' columns, which staff fill on the day money arrives)
        pays = (await s.execute(text("""
            SELECT tc.id AS tenancy_id, r.room_number, t.name, t.phone,
                   p.amount, p.payment_mode::text AS mode,
                   p.for_type::text AS for_type, p.period_month, p.payment_date
            FROM payments p
            JOIN tenancies tc ON tc.id = p.tenancy_id
            JOIN tenants   t  ON t.id  = tc.tenant_id
            LEFT JOIN rooms r ON r.id  = tc.room_id
            WHERE p.is_void = false
              AND p.payment_date BETWEEN :d1 AND :d2
        """), {"d1": SEP_FROM, "d2": SEP_TO})).mappings().all()

        # Sep rent booked earlier (collected in late Aug) — otherwise it reads
        # as "missing from the app" when the sheet has it in a Sep column
        pre_sep = (await s.execute(text("""
            SELECT tc.id AS tenancy_id, p.amount, p.payment_mode::text AS mode
            FROM payments p
            JOIN tenancies tc ON tc.id = p.tenancy_id
            WHERE p.is_void = false
              AND p.payment_date < :d1 AND p.period_month = :pm
        """), {"d1": SEP_FROM, "pm": PERIOD})).mappings().all()

        day = (await s.execute(text("""
            SELECT room_number, guest_name, phone, checkin_date, checkout_date,
                   num_days, total_amount, booking_amount, status
            FROM daywise_stays
            WHERE checkin_date BETWEEN :d1 AND :d2
        """), {"d1": SEP_FROM, "d2": SEP_TO})).mappings().all()
    return tenancies, pays, pre_sep, day


STATUS_RANK = {"active": 0, "exited": 1, "no_show": 2, "cancelled": 3}


class Person:
    """All tenancy rows belonging to one human.

    A person routinely holds several tenancy rows (re-booking, room move, a
    cancelled pre-registration into placeholder room 000). Matching a sheet row
    against raw tenancy rows picks whichever row sorts first, so an old exited
    row swallows the match and the live one is reported as 'not in the sheet'
    while the sheet row is reported as 'missing in the app' — the same money
    counted as two opposite errors. Collapse to the person first.
    """

    __slots__ = ("names", "phones", "rooms", "tenancies", "cash", "upi",
                 "other", "pre_sep", "due")

    def __init__(self):
        self.names: list[str] = []
        self.phones: set[str] = set()
        self.rooms: set[str] = set()
        self.tenancies: list[dict] = []
        self.cash = self.upi = self.other = self.pre_sep = self.due = 0.0

    @property
    def best(self):
        """The tenancy that represents this person now: live one wins, and a
        real room always beats the 000 placeholder."""
        return min(self.tenancies, key=lambda d: (
            norm_room(d["room_number"]) in ("", "000"),
            STATUS_RANK.get(d["status"], 9),
            -(d["checkin_date"].toordinal() if d["checkin_date"] else 0),
        ))

    @property
    def display(self):
        return max(self.names, key=len) if self.names else "(unknown)"

    @property
    def room(self):
        return norm_room(self.best["room_number"])

    @property
    def status(self):
        return self.best["status"]

    @property
    def paid(self):
        return self.cash + self.upi + self.other


def build_people(tenancies, paid_by_tenancy, pre_by_tenancy):
    people: list[Person] = []
    by_phone: dict[str, Person] = {}

    for d in tenancies:
        ph = phone10(d["phone"])
        nm = norm_name(d["name"])
        room = norm_room(d["room_number"])
        p = by_phone.get(ph) if ph else None
        if p is None:
            for q in people:
                if any(similar(n, nm) for n in q.names) and (room in q.rooms or not room):
                    p = q
                    break
        if p is None:
            p = Person()
            people.append(p)
        if ph:
            p.phones.add(ph)
            by_phone.setdefault(ph, p)
        if nm not in p.names:
            p.names.append(nm)
        if room:
            p.rooms.add(room)
        p.tenancies.append(d)
        # only a live tenancy carries this month's rent obligation; a cancelled
        # or no-show duplicate must not double-bill the person
        if d["status"] in ("active", "exited"):
            p.due += float(d["due"] or 0)
        m = paid_by_tenancy.get(d["id"])
        if m:
            p.cash += m["cash"]
            p.upi += m["upi"]
            p.other += m["other"]
        p.pre_sep += pre_by_tenancy.get(d["id"], 0.0)
    return people, by_phone


def match(sheet_row, people, used, by_phone=None):
    """Phone first, then room+name, then name alone. Never reuses a person."""
    ph = sheet_row["phone"]
    if ph and by_phone is not None:
        p = by_phone.get(ph)
        if p is not None and id(p) not in used:
            return p
    for p in people:
        if id(p) in used:
            continue
        if sheet_row["room"] in p.rooms and any(similar(n, sheet_row["name"]) for n in p.names):
            return p
    for p in people:
        if id(p) in used:
            continue
        if any(similar(n, sheet_row["name"]) for n in p.names):
            return p
    return None




async def main():
    sh = open_sheet()
    lt = read_long_term(sh)
    dw = read_daywise(sh)
    tenancies, pays, pre_sep, day = await load_db()

    paid_by_tenancy: dict[int, dict] = {}
    for p in pays:
        e = paid_by_tenancy.setdefault(p["tenancy_id"],
                                       {"cash": 0.0, "upi": 0.0, "other": 0.0})
        amt = float(p["amount"])
        e["cash" if p["mode"] == "cash" else "upi" if p["mode"] == "upi" else "other"] += amt
    pre_by_tenancy: dict[int, float] = {}
    for p in pre_sep:
        pre_by_tenancy[p["tenancy_id"]] = pre_by_tenancy.get(p["tenancy_id"], 0.0) + float(p["amount"])

    people, by_phone = build_people(tenancies, paid_by_tenancy, pre_by_tenancy)

    used: set[int] = set()
    matched, unmatched_sheet = [], []
    for r in lt:
        p = match(r, people, used, by_phone)
        if p is None:
            unmatched_sheet.append(r)
            continue
        used.add(id(p))
        matched.append((r, p))
    unmatched_db = [p for p in people if id(p) not in used]

    print("=" * 100)
    print("SEPTEMBER 2026 — BACKUP SHEET vs APP")
    print("=" * 100)
    print(f"sheet 'September Long Term' rows      : {len(lt)}")
    print(f"app people with a tenancy alive in Sep: {len(people)}  (from {len(tenancies)} tenancy rows)")
    print(f"matched                               : {len(matched)}")
    print(f"in sheet, NOT matched in app          : {len(unmatched_sheet)}")
    print(f"in app, NOT matched in sheet          : {len(unmatched_db)}")

    # ---------------- money -----------------
    sheet_cash = sum(r["sep_cash"] for r in lt)
    sheet_upi = sum(r["sep_upi"] for r in lt)
    db_cash = sum(v["cash"] for v in paid_by_tenancy.values())
    db_upi = sum(v["upi"] for v in paid_by_tenancy.values())
    db_other = sum(v["other"] for v in paid_by_tenancy.values())
    print("\n--- SEPTEMBER MONEY (every payment type) ---")
    print(f"{'':<20}{'SHEET':>14}{'APP':>14}{'APP-SHEET':>14}")
    print(f"{'cash':<20}{sheet_cash:>14,.0f}{db_cash:>14,.0f}{db_cash-sheet_cash:>14,.0f}")
    print(f"{'upi':<20}{sheet_upi:>14,.0f}{db_upi:>14,.0f}{db_upi-sheet_upi:>14,.0f}")
    print(f"{'other/unknown mode':<20}{0:>14,.0f}{db_other:>14,.0f}{db_other:>14,.0f}")
    print(f"{'TOTAL':<20}{sheet_cash+sheet_upi:>14,.0f}{db_cash+db_upi+db_other:>14,.0f}"
          f"{db_cash+db_upi+db_other-sheet_cash-sheet_upi:>14,.0f}")

    by_for: dict[str, float] = {}
    for p in pays:
        by_for[p["for_type"]] = by_for.get(p["for_type"], 0.0) + float(p["amount"])
    print("\napp money received in Sep, by for_type:")
    for k, v in sorted(by_for.items(), key=lambda z: -z[1]):
        print(f"   {k:<22}{v:>14,.0f}")
    rent_periods: dict[str, float] = {}
    for p in pays:
        if p["for_type"] == "rent":
            key = str(p["period_month"])
            rent_periods[key] = rent_periods.get(key, 0.0) + float(p["amount"])
    print("\napp RENT received in Sep, by the period_month it settles:")
    for k, v in sorted(rent_periods.items()):
        print(f"   {k:<22}{v:>14,.0f}")

    # ---------------- per-tenant money diffs -----------------
    print("\n--- PER-TENANT COLLECTION DIFFERENCES (Sep) ---")
    diffs = []
    for r, p in matched:
        s_tot = r["sep_cash"] + r["sep_upi"]
        a_tot = p.paid
        if abs(s_tot - a_tot) < 1 and abs(r["sep_cash"] - p.cash) < 1:
            continue
        diffs.append((r, p, s_tot, a_tot))
    diffs.sort(key=lambda z: -abs(z[2] - z[3]))
    print(f"{'Room':<7}{'Name':<26}{'ShCash':>9}{'AppCash':>9}"
          f"{'ShUPI':>9}{'AppUPI':>9}{'Diff':>10}  Note")
    for r, p, s_tot, a_tot in diffs:
        note = []
        if p.pre_sep:
            note.append(f"app booked Rs {p.pre_sep:,.0f} for Sep before 1 Sep")
        if p.other:
            note.append(f"Rs {p.other:,.0f} with other/no mode")
        if a_tot and abs(s_tot - a_tot) < 1:
            note.append("same total, MODE differs")
        elif a_tot > s_tot:
            note.append("APP HAS MORE")
        else:
            note.append("MISSING IN APP")
        print(f"{r['room']:<7}{r['raw_name'][:25]:<26}{r['sep_cash']:>9,.0f}{p.cash:>9,.0f}"
              f"{r['sep_upi']:>9,.0f}{p.upi:>9,.0f}{a_tot-s_tot:>10,.0f}  {'; '.join(note)}")
    net = sum(z[3] - z[2] for z in diffs)
    print(f"\n{len(diffs)} tenants differ, net Rs {net:,.0f}")

    # ---------------- check-ins -----------------
    print("\n--- SEPTEMBER CHECK-INS ---")
    sheet_ci = [r for r in lt if r["checkin"] and SEP_FROM <= r["checkin"] <= SEP_TO]
    db_ci = [p for p in people
             if any(d["checkin_date"] and SEP_FROM <= d["checkin_date"] <= SEP_TO
                    for d in p.tenancies)]
    print(f"sheet: {len(sheet_ci)}   app: {len(db_ci)}")
    ci_used: set[int] = set()
    for r in sheet_ci:
        p = match(r, db_ci, ci_used, None)
        if p:
            ci_used.add(id(p))
            dbci = [d["checkin_date"] for d in p.tenancies
                    if d["checkin_date"] and SEP_FROM <= d["checkin_date"] <= SEP_TO]
            if r["checkin"] not in dbci:
                print(f"  DATE DIFF  {r['room']:<6}{r['raw_name'][:28]:<30}"
                      f" sheet {r['checkin']}  app {', '.join(str(x) for x in dbci)}")
        else:
            p2 = match(r, people, set(), by_phone)
            where = (f"in app, but check-in {p2.best['checkin_date']} ({p2.status})"
                     if p2 else "NOT IN THE APP AT ALL")
            print(f"  SHEET ONLY {r['room']:<6}{r['raw_name'][:28]:<30} {r['checkin']}  -> {where}")
    for p in db_ci:
        if id(p) not in ci_used:
            d = p.best
            print(f"  APP ONLY   {p.room:<6}{p.display[:28]:<30} {d['checkin_date']} ({p.status})"
                  f"  paidSep={p.paid:,.0f}")

    # ---------------- check-outs -----------------
    print("\n--- SEPTEMBER CHECK-OUTS / EXITS ---")
    sheet_exit = [r for r in lt if r["status"] == "EXIT"]
    db_exit = [p for p in people
               if any(d["checkout_date"] and SEP_FROM <= d["checkout_date"] <= SEP_TO
                      for d in p.tenancies)]
    print(f"sheet rows marked EXIT: {len(sheet_exit)}"
          f"   app people with a Sep checkout date: {len(db_exit)}")
    ex_used: set[int] = set()
    no_checkout_date = []
    for r in sheet_exit:
        p = match(r, people, set(), by_phone)
        if p is None:
            print(f"  SHEET ONLY   {r['room']:<6}{r['raw_name'][:28]:<30} -> not in the app")
            continue
        ex_used.add(id(p))
        if any(d["checkout_date"] and SEP_FROM <= d["checkout_date"] <= SEP_TO for d in p.tenancies):
            continue
        if p.status == "active":
            print(f"  STILL ACTIVE {r['room']:<6}{r['raw_name'][:28]:<30}"
                  f" sheet says EXIT, app says active — the bed still reads occupied")
        else:
            no_checkout_date.append((r, p))
    if no_checkout_date:
        print(f"\n  {len(no_checkout_date)} more are exited/cancelled/no-show in the app but carry"
              f" NO checkout_date, so no Sep checkout report can see them:")
        for r, p in no_checkout_date:
            print(f"     {r['room']:<6}{r['raw_name'][:28]:<30} app status={p.status}")
    for p in db_exit:
        if id(p) not in ex_used:
            d = [x["checkout_date"] for x in p.tenancies if x["checkout_date"]]
            print(f"  APP ONLY     {p.room:<6}{p.display[:28]:<30} checkout {max(d)} ({p.status})")

    # ---------------- unmatched -----------------
    if unmatched_sheet:
        print("\n--- IN THE SHEET, NOT FOUND IN THE APP ---")
        for r in sorted(unmatched_sheet, key=lambda z: room_key(z["room"])):
            print(f"  {r['room']:<7}{r['raw_name'][:30]:<32}{r['phone']:<12} sheet={r['status']:<8}"
                  f" sep={r['sep_state'][:10]:<11} cash={r['sep_cash']:>8,.0f} upi={r['sep_upi']:>8,.0f}")

    print("\n--- IN THE APP, NOT FOUND IN THE SHEET ---")
    live_missing = [p for p in unmatched_db if p.due or p.paid or p.status == "active"]
    quiet = len(unmatched_db) - len(live_missing)
    for p in sorted(live_missing, key=lambda z: room_key(z.room)):
        print(f"  {p.room:<7}{p.display[:30]:<32}{(next(iter(p.phones)) if p.phones else ''):<12}"
              f"status={p.status:<9} due={p.due:>9,.0f} paidSep={p.paid:>9,.0f}")
    print(f"  ({quiet} more are exited/cancelled with no Sep money and no Sep due — ignorable)")

    # ---------------- day wise -----------------
    print("\n--- DAY-WISE (September check-ins) ---")
    print(f"sheet: {len(dw)}   app daywise_stays: {len(day)}")
    day_left = list(day)
    for r in dw:
        hit = None
        for d in day_left:
            if (phone10(d["phone"]) and phone10(d["phone"]) == r["phone"]) or (
                    norm_room(d["room_number"]) == r["room"]
                    and similar(norm_name(d["guest_name"]), r["name"])):
                hit = d
                break
        if hit is None:
            print(f"  SHEET ONLY {r['room']:<6}{r['raw_name'][:26]:<28}{r['checkin']} "
                  f"{r['days']}d total={r['total']:,.0f} dues={r['dues']:,.0f}")
            continue
        day_left.remove(hit)
        if abs(float(hit["total_amount"] or 0) - r["total"]) >= 1:
            print(f"  AMT DIFF   {r['room']:<6}{r['raw_name'][:26]:<28}"
                  f"sheet {r['total']:,.0f}  app {float(hit['total_amount'] or 0):,.0f}")
        if hit["checkin_date"] != r["checkin"]:
            print(f"  DATE DIFF  {r['room']:<6}{r['raw_name'][:26]:<28}"
                  f"sheet {r['checkin']}  app {hit['checkin_date']}")
    for d in day_left:
        print(f"  APP ONLY   {norm_room(d['room_number']):<6}{d['guest_name'][:26]:<28}"
              f"{d['checkin_date']} total={float(d['total_amount'] or 0):,.0f}")
    print(f"\nsheet day-wise Sep revenue : {sum(r['total'] for r in dw):,.0f}")
    print(f"app   day-wise Sep revenue : {sum(float(d['total_amount'] or 0) for d in day):,.0f}")


if __name__ == "__main__":
    asyncio.run(main())
