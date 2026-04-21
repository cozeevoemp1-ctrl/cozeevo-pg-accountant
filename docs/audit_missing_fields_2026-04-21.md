# Missing-Info Audit — Active / No-Show Tenancies

Date: 2026-04-21. Scope: DB `Tenancy` rows with status ∈ {active, no_show}.

## 1. Room UNASSIGNED (5 tenants)

Future check-ins — source sheet has "May"/"June" or blank in the Room column. Assign a real room when they arrive.

- Ayush Kolte (checkin May)
- Diksha (May)
- Prasad Vadlamani (May)
- Kiran Koushik (June)
- Nihanth (June)

## 2. Floor missing on Room record (32 rooms)

All G-block (ground floor) rooms — `Room.floor` is NULL. **Data issue on the `rooms` table**, not the tenancy. Fix: set `floor = 0` or `'G'` on all G-prefix rooms once and it carries forward for every tenant.

Affected rooms: G01, G02, G03, G04, G07, G08, G09, G10, G11, G13, G14, G15, G16, G17, G18, G19 (+ 2 UNASSIGNED rows).

## 3. Deposit = 0 (10 tenants)

| Room | Name |
|---|---|
| G17 | Lokesh Sanaka |
| 414 | Dhruv |
| 216 | Arun Vasavan |
| 115 | Mamta Khandade |
| 424 | Lakshita Jain |
| 616 | Omkar Deodher |
| 616 | Swarup Ravindra Futane |
| 522 | Adithya Reddy |
| 112 | Chinmay Pagey |
| 621 | Sajith |

Either genuine (staff/waivers) or missing data — check source sheet col G.

## 4. Yash Shinde (416) — Floor cell empty in TENANTS tab

Room 416 has `floor=4` in `rooms` table — data is fine on the Room record. TENANTS sheet just needed resync. `sync_tenant_all_fields(834)` run: 9 cells updated. Refresh the sheet.

## 5. All clear

- agreed_rent = 0: **0** (was 5, all fixed)
- gender missing: 0
- phone missing: 0
- checkin_date missing: 0
- sharing_type missing: 0
