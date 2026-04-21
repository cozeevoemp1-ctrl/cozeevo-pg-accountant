# Room/Sharing/Rent Anomalies — 2026-04-21

Scope: active + no_show tenancies. Ran after Rakesh 415 dupe merge.

## 1. Mixed sharing type in same room (2 rooms)

| Room | Tenants | Issue |
|---|---|---|
| **416** | Naitik Raj (double, Rs.13000) + Yash Shinde (single, Rs.0) | Yash source cell blank — is this room single-occupancy (just Yash) or double-occupancy with both? |
| **610** | Akshayarathna A (double, Rs.12250) + Baisali Das (single, Rs.12500) | Same person in two different sharing classifications? |

## 2. Same sharing, different rent in same room (46 rooms)

Mostly ±500–1000 variance (grandfathered older tenants vs new rates). Flag outliers below.

### Large gaps (Rs.1500+)

| Room | Sharing | Tenants | Rents |
|---|---|---|---|
| **602** | double | Mahika Yerneni / Sumedha | 15500 / **26000** (26k looks like premium rate misapplied) |
| **508** | double | Shravya / Devika | 15000 / 13000 |
| **405** | double | Jerome Babu / Anush | 13000 / 12500 (Anush checkin only) |
| **511** | double | Jaya Prakash / Kamesh | 14500 / 13000 |
| **G17** | double | Lokesh Sanaka / Rakesh Sanaka / Ajay Ramchandra | 13500 / 13500 / 12000 — **3 tenants in a double room** |

### Staff rooms (G17)
G17 has 3 tenants including 2 staff (Lokesh, Rakesh Sanaka). Check if it should be flagged as staff room.

## 3. Suggested actions (Kiran)

- **Room 416**: confirm sharing type + Yash's rent (already pending from earlier task).
- **Room 610**: pick one sharing type for both tenants.
- **Room 602 Sumedha**: 26k on a "double" sharing row looks like premium misclassified. Audit.
- **Room G17**: 3 tenants in 1 double — confirm as triple or split. Also resolves rent mismatch.
- Rest (45 rooms with ±500–1000 variance): likely historical pricing, leave unless bulk-normalization is desired.
