# Google Sheet Workflow — Cozeevo Operations

## Sheet Structure (5 sheets)

| Sheet | Who Fills It | When | Purpose |
|-------|-------------|------|---------|
| **ROOMS** | Admin only | Rarely (physical changes) | Room master: number, building, type, beds, staff flag |
| **TENANTS** | Admin only | On check-in / checkout / changes | One row per tenant forever, update Status |
| **PAYMENTS** | Receptionist | Daily (one row per payment) | Append-only ledger: date, tenant, amount, mode, month |
| **CHANGES LOG** | Admin only | When anything changes | Rent change, room transfer, sharing change |
| **DASHBOARD** | Nobody | Auto-calculated from above sheets | Occupancy, collections, who hasn't paid |

---

## Daily Workflow — Receptionist

### When rent is received:
1. Open **PAYMENTS** sheet
2. Add one row:

| Date | Tenant | Room | Amount | Mode | For Month | Type | Received By | Notes |
|------|--------|------|--------|------|-----------|------|-------------|-------|
| 2026-03-27 | Raj Kumar | 203 | 15000 | UPI | Mar 2026 | Rent | | |

3. Done. Takes 10 seconds.

### If someone pays for multiple months:
Add **separate rows** for each month:

| Date | Tenant | Room | Amount | Mode | For Month | Type |
|------|--------|------|--------|------|-----------|------|
| 2026-03-27 | Soham Das | 306 | 7500 | Cash | Feb 2026 | Rent |
| 2026-03-27 | Soham Das | 306 | 12800 | Cash | Mar 2026 | Rent |

### If deposit is received:
| Date | Tenant | Room | Amount | Mode | For Month | Type |
|------|--------|------|--------|------|-----------|------|
| 2026-03-27 | New Person | 209 | 15000 | UPI | | Deposit |

(Leave "For Month" empty for deposits)

---

## Weekly Workflow — Admin

### Check Dashboard:
1. Open **DASHBOARD** sheet
2. Set month in cell B3 (e.g., `2026-03-01`)
3. Read: occupancy, collections, pending amounts
4. Cross-check with bank account

### Who hasn't paid?
Compare active tenants in **TENANTS** sheet with payments in **PAYMENTS** sheet for the month. Anyone active with no payment row = hasn't paid.

---

## When Events Happen — Admin

### New tenant checks in:
1. **TENANTS** sheet: Add new row

| Name | Phone | Room | Building | Rent | Deposit | Sharing | Stay Type | Check-in | Status |
|------|-------|------|----------|------|---------|---------|-----------|----------|--------|
| New Person | 9876543210 | 209 | THOR | 12800 | 15000 | Double | Monthly | 2026-03-27 | Active |

2. **PAYMENTS** sheet: Log deposit if received

### Tenant checks out:
1. **TENANTS** sheet: Update existing row
   - Status → `Exited`
   - Checkout Date → `2026-03-27`
   - (Don't delete the row — just change Status)

2. **PAYMENTS** sheet: Log refund if applicable (Type = Refund, negative amount or separate row)

### Rent changes:
1. **TENANTS** sheet: Update Rent column to new amount
2. **CHANGES LOG**: Record what changed

| Date | Tenant | Room | Change | Old Value | New Value | Notes |
|------|--------|------|--------|-----------|-----------|-------|
| 2026-04-01 | Raj Kumar | 203 | Rent | 12800 | 15000 | Annual revision |

### Room transfer:
1. **TENANTS** sheet: Update Room + Building columns
2. **CHANGES LOG**:

| Date | Tenant | Room | Change | Old Value | New Value | Notes |
|------|--------|------|--------|-----------|-----------|-------|
| 2026-04-01 | Raj Kumar | 301 | Room | 203 | 301 | Requested upgrade |

### Premium → Double sharing:
1. **TENANTS** sheet: Update Sharing column
2. **CHANGES LOG**:

| Date | Tenant | Room | Change | Old Value | New Value | Notes |
|------|--------|------|--------|-----------|-----------|-------|
| 2026-04-01 | Anuron Dutta | 105 | Sharing | Premium | Double | Roommate added |

### No-show tenant:
1. **TENANTS** sheet: Status = `No-show` (keep the row, don't delete)
2. When they finally arrive: Status → `Active`, update Check-in date

### Daily/temporary stay:
1. **TENANTS** sheet: Add row with Stay Type = `Daily`, fill both Check-in AND Checkout Date
2. **PAYMENTS** sheet: Log total amount (Type = Rent, For Month = stay month)

---

## What NOT To Do

| Wrong | Right |
|-------|-------|
| Delete a tenant row when they leave | Change Status to Exited |
| Add new columns every month | Add rows to PAYMENTS sheet |
| Mix text and numbers in payment cells | Numbers only in Amount, notes in Notes column |
| Write "paid in feb" in March column | Use separate row: For Month = Feb 2026 |
| Write "received by Chandra" in amount cell | Use Received By column |
| Hard-delete payment rows | Add a new row with Type = Void |

---

## How the Bot Syncs

When a payment is logged via WhatsApp:
1. Bot writes to Supabase DB (primary)
2. Bot writes to **PAYMENTS** sheet (fire-and-forget sync)
3. If sheet write fails, DB record still exists

When data is entered manually in the sheet:
- Bot does NOT read from the sheet for calculations
- DB is the source of truth for the bot
- Sheet is the source of truth for manual tracking

### Keeping both in sync:
- Payments logged via bot → auto-synced to both DB + sheet
- Payments logged manually in sheet → NOT in DB (admin must also log via bot)
- Best practice: always log via bot, check sheet for visual confirmation

---

## Month-End Checklist

1. **Check DASHBOARD** — occupancy, collection, pending
2. **Review PAYMENTS** — any missing entries? Cross-check with bank
3. **Update TENANTS** — any new no-shows? Exits? Rent changes?
4. **CHANGES LOG** — record any changes made this month
5. **Screenshot DASHBOARD** — save for records

---

## Setup Instructions

### First time (one-time):
```bash
python scripts/create_new_gsheet.py --write
```
This creates the sheet and populates from DB. Share the URL with team.

### To update existing sheet:
```bash
python scripts/create_new_gsheet.py --write --id YOUR_SHEET_ID
```

### To update gsheets.py integration:
After the new sheet is live, update `src/integrations/gsheets.py` to write to PAYMENTS sheet format instead of the old column-based format.

---

## Column Reference

### ROOMS
| Column | Description | Example |
|--------|-------------|---------|
| Room | Room number | G01, 105, 523 |
| Building | THOR or HULK | THOR |
| Floor | 0=ground, 1-6 | 1 |
| Type | single/double/triple | double |
| Max Beds | Bed capacity | 2 |
| Staff Room | Yes/No | No |
| AC | Yes/No | No |

### TENANTS
| Column | Description | Example |
|--------|-------------|---------|
| Name | Full name | Raj Kumar |
| Phone | WhatsApp number | 9876543210 |
| Room | Current room | 203 |
| Building | THOR/HULK | THOR |
| Rent | Current monthly rent | 15000 |
| Deposit | Security deposit | 15000 |
| Sharing | single/double/triple/premium | Double |
| Stay Type | Monthly/Daily | Monthly |
| Check-in | Move-in date | 2026-01-15 |
| Status | Active/Exited/No-show | Active |
| Checkout Date | Exit date (empty if active) | 2026-03-27 |
| Notice Date | When notice given | 2026-03-01 |
| Gender | M/F | M |
| Notes | Special agreements | Hitachi booking |

### PAYMENTS
| Column | Description | Example |
|--------|-------------|---------|
| Date | Payment date | 2026-03-27 |
| Tenant | Name | Raj Kumar |
| Room | Room number | 203 |
| Amount | Payment amount (numbers only) | 15000 |
| Mode | CASH / UPI | UPI |
| For Month | Which month it covers | Mar 2026 |
| Type | Rent/Deposit/Refund/Maintenance | Rent |
| Received By | Who collected | Chandra |
| Notes | Any remarks | partial payment |
