# Cozeevo Master Data (L0)

> **Owner-controlled. Changes only when physical layout or staff allocation changes.**
> This is NOT transactional data. Do not derive from Excel snapshots.

---

## Data Pyramid

```
L0 — MASTER DATA (this file)
    Physical rooms, buildings, staff rooms, bed counts
    Changes: only when owner adds/removes rooms or reassigns staff rooms
    Source of truth: owner confirmation

L1 — OPERATIONAL DATA (Supabase tables)
    Tenants, tenancies (who is in which room), rent amounts, deposits
    Changes: on every check-in, check-out, rent revision
    Source of truth: Supabase DB (imported from Excel snapshots)

L2 — FINANCIAL DATA (bank statements + payments table)
    Payments received, expenses paid, bank transactions
    Changes: daily (every UPI/cash payment, every expense)
    Source of truth: bank statement Excel + Supabase payments table

L3 — DERIVED / REPORTS (calculated, never stored)
    Occupancy %, collection rate, P&L, dues outstanding
    Changes: recalculated on every query
    Source of truth: computed from L0 + L1 + L2
```

**Rule:** Higher layers never override lower layers. If L3 (report) conflicts with L0 (master), L0 wins.

---

## Buildings

| Property | Floors | Rooms/Floor | Floor 7 | Ground | Total Rooms |
|---|---|---|---|---|---|
| Cozeevo THOR | G + 1-6 + 7 | 12 (x01-x12) | 701, 702 | G01-G10 | **84** |
| Cozeevo HULK | G + 1-6 | 12 (x13-x24) | none | G11-G20 | **82** |
| **Total** | | | | | **166** (8 staff, 158 revenue) |

### Room Numbering Convention
- THOR: `{floor}{01-12}` — e.g. 101, 212, 312, 601
- HULK: `{floor}{13-24}` — e.g. 113, 224, 324, 624
- Ground: THOR = G01-G10, HULK = G11-G20
- Floor 7: THOR only = 701, 702

---

## Staff Rooms (excluded from revenue)

> **Live source of truth:** `rooms.is_staff_room = True` in Supabase.
> **Update this table + BRAIN.md** whenever a room is permanently added or removed as staff quarters.

| Room | Property | Beds | Notes |
|---|---|---|---|
| G05 | THOR | 3 | Staff quarters (permanent) |
| G06 | THOR | 2 | Staff quarters (permanent) |
| 107 | THOR | 2 | Staff quarters (permanent) |
| 108 | THOR | 2 | Staff quarters (permanent) |
| 701 | THOR | 1 | Staff quarters (permanent) |
| 702 | THOR | 1 | Staff quarters (permanent) |
| G12 | HULK | 3 | Staff quarters (permanent) |
| G20 | HULK | 1 | Staff quarters (temporary — until April 2026 end, returns to revenue May 2026) |

**Total staff rooms: 8** (THOR 6 + HULK 2) — **294 revenue beds currently; 295 from May 2026 when G20 returns**

> **Changed 2026-04-26:** 114 and 618 moved from staff → revenue (paying tenants moved in). G20 moved to staff temporarily until April end.

---

## Revenue Rooms & Beds

| Property | Revenue Rooms | Single (1 bed) | Double (2 bed) | Triple (3 bed) | Total Beds |
|---|---|---|---|---|---|
| THOR | 78 | 14 | 61 | 3 | **145** |
| HULK | 80 | 13 | 65 | 2 | **149** |
| **Total** | **158** | **27** | **126** | **5** | **294** |

> When G20 returns to revenue (May 2026): HULK singles = 14, HULK total = 150, grand total = **295**.

### Bed Count Formula
```
Total Revenue Beds = SUM(max_occupancy) for all non-staff rooms
                   = (single rooms x 1) + (double rooms x 2) + (triple rooms x 3)
                   = 27 + 252 + 15
                   = 294  (295 when G20 returns)
```

### Corner Room Rule (applies to BOTH buildings)
- First room on each floor (x01 THOR / x13 HULK) = **single** (1 bed)
- Last room on each floor (x12 THOR / x24 HULK) = **single** (1 bed)
- Ground floor first (G01 THOR / G11 HULK) = **single** (1 bed)
- Ground floor last (G10 THOR / G20 HULK) = **single** (1 bed) — G20 currently staff
- Floor 7: 702 (THOR only) = **single** (1 bed, staff)

---

## Premium — NOT a Room Type

"Premium" is an **operational status**, not a physical room attribute.
- A premium occupancy means 1 tenant is living alone in a double/triple room
- The room physically still has 2 or 3 beds
- Premium status is tracked on the **tenancy**, not the room
- A room can be premium this month and double-sharing next month
- For occupancy calculation: 1 premium tenant = 1 occupied bed (NOT 2)
- For revenue: premium tenant pays a higher rent (covers the empty bed)

**Never hardcode a room as "premium" in the rooms table.**

---

## Occupancy Calculation Rules

```
Total Capacity     = SUM(max_occupancy) for all non-staff rooms (currently 294)
                     Calculated dynamically from rooms table, never hardcoded.

Occupied Beds      = SUM(
                       IF sharing_type = 'premium' THEN room.max_occupancy  -- full room
                       ELSE 1                                                -- 1 bed per person
                     )
                     Only count tenancies with sharing_type = 'premium' as multi-bed.
                     A person alone in a double room WITHOUT premium booking = 1 bed.

Vacant Beds        = Total Capacity - Occupied Beds
Occupancy %        = Occupied Beds / Total Capacity x 100

For a specific month M:
  Occupied = tenancies WHERE checkin_date <= last_day(M)
             AND (status = active OR checkout_date >= first_day(M))

Reporting format:
  Checked-in:  X people (Y regular + Z premium)
  Active beds: (Y × 1) + (Z × room.max_occupancy)
  No-show:     N people (N beds reserved)  ← shown separately
  Total beds held: active beds + no-show
```

### Premium Booking Rule
- Premium = tenant **explicitly booked and paid** for the full room at premium rate
- It is a **tenancy attribute** (`sharing_type = 'premium'`), NOT a room attribute
- 1 person in a double room who did NOT book premium = `sharing_type = 'double'`, 1 bed occupied
- Only `sharing_type = 'premium'` triggers the multi-bed count
- A room can have premium tenant today and double-sharing tenants tomorrow

---

## THOR Room Layout (78 revenue + 6 staff = 84)

| Floor | Rooms | Count | Sharing Types |
|---|---|---|---|
| G | G01-G10 | 10 | G01=1, G02-G04=2, **G05=staff**, **G06=staff**, G07-G09=3, G10=1 |
| 1 | 101-112 | 12 | 101=1, 102-106=2, **107=staff**, **108=staff**, 109-111=2, 112=1 |
| 2 | 201-212 | 12 | 201=1, 202-211=2, 212=1 |
| 3 | 301-312 | 12 | 301=1, 302-311=2, 312=1 |
| 4 | 401-412 | 12 | 401=1, 402-411=2, 412=1 |
| 5 | 501-512 | 12 | 501=1, 502-511=2, 512=1 |
| 6 | 601-612 | 12 | 601=1, 602-611=2, 612=1 |
| 7 | 701-702 | 2 | **701=staff**, **702=staff** |

## HULK Room Layout (80 revenue + 2 staff = 82)

| Floor | Rooms | Count | Sharing Types |
|---|---|---|---|
| G | G11-G20 | 10 | G11=1, **G12=staff**, G13-G14=3, G15-G19=2, **G20=staff(temp)** |
| 1 | 113-124 | 12 | 113=1, 114=2, 115-123=2, 124=1 |
| 2 | 213-224 | 12 | 213=1, 214-223=2, 224=1 |
| 3 | 313-324 | 12 | 313=1, 314-323=2, 324=1 |
| 4 | 413-424 | 12 | 413=1, 414-423=2, 424=1 |
| 5 | 513-524 | 12 | 513=1, 514-523=2, 524=1 |
| 6 | 613-624 | 12 | 613=1, 614-617=2, 618=2, 619-623=2, 624=1 |

---

## Changelog
- 2026-03-23: Initial master data created from owner confirmation
- 2026-04-27: Fixed room 120 max_occupancy 3→2 in DB (was a data entry error; docs always said double). Total revenue beds confirmed 294 for April 2026.
- 2026-04-26: 114 + 618 moved from staff → revenue. G20 moved to staff (temporary, until April 2026 end — returns to revenue May 2026). G05 corrected to staff (was wrongly revenue in DB). G13 corrected to room_type=triple in DB. Revenue beds: 291 → 294 (295 from May 2026).
