"""
One-off: P&L Oct'25–Mar'26, bank only.
  - Cash income line excluded
  - Property Rent (Cash) excluded from OPEX
  - Security Deposits TOTAL column = net held at period end (received - refunded)
  - Deposits Refunded TOTAL = YTD reference (kept for visibility)
Output: data/reports/PnL_Oct25_Mar26_BankOnly.xlsx
DO NOT modify pnl_builder.py — this script patches in-memory only.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import src.reports.pnl_builder as pb
from src.reports.pnl_builder import build_pnl_workbook
from openpyxl.styles import Font

KEEP = slice(0, 6)  # Oct'25–Mar'26

# ── Patch module-level data ───────────────────────────────────────────────────
pb.MONTHS = ["Oct'25", "Nov'25", "Dec'25", "Jan'26", "Feb'26", "Mar'26"]

# Remove cash income line; slice to 6 months
pb.INCOME = {
    k: v[KEEP]
    for k, v in pb.INCOME.items()
    if "Cash (physical" not in k
}

# Remove cash rent from OPEX; slice to 6 months
pb.OPEX = {
    k: v[KEEP]
    for k, v in pb.OPEX.items()
    if "Cash paid" not in k
}

pb.CAPITAL_CONTRIBUTIONS = {k: v[KEEP] for k, v in pb.CAPITAL_CONTRIBUTIONS.items()}
pb.EXCLUDED              = {k: v[KEEP] for k, v in pb.EXCLUDED.items()}
pb.DEPOSITS              = {k: v[KEEP] for k, v in pb.DEPOSITS.items()}

pb.BANK_BALANCE_THOR = {k: v for k, v in pb.BANK_BALANCE_THOR.items() if k != "Apr'26"}
pb.BANK_BALANCE_HULK = {k: v for k, v in pb.BANK_BALANCE_HULK.items() if k != "Apr'26"}
pb.BANK_CLOSING_BALANCE_THOR = pb.BANK_BALANCE_THOR["Mar'26"][1]
pb.BANK_CLOSING_BALANCE_HULK = pb.BANK_BALANCE_HULK["Mar'26"][1]

# ── Build workbook ────────────────────────────────────────────────────────────
wb = build_pnl_workbook()

# No post-processing needed — pnl_builder handles deposit TOTAL correctly (closing balance of last month)

# ── Save ─────────────────────────────────────────────────────────────────────
OUT = Path(__file__).parent.parent / "data" / "reports" / "PnL_Oct25_Mar26_BankOnly.xlsx"
OUT.parent.mkdir(parents=True, exist_ok=True)
wb.save(OUT)
print(f"Saved: {OUT}")

# Print key summary figures
print()
print("Key figures (bank only, Oct'25–Mar'26):")
gross  = 8_817_581
sec    = -1_366_289  # net held (TOTAL col)
refund = -375_261    # YTD refunded
opex_nocash = (
    0+0+0+0+600000+605140       # rent bank
  + 0+0+74768+131554+134538+96617   # electricity
  + 0+0+0+0+0+8000              # water
  + 0+0+3480+12068+934+1128     # IT
  + 0+0+43946+70730+113168+0    # wifi
  + 0+33632+113787+217504+115595+240294  # food
  + 0+0+1200+9599+105866+364161  # fuel
  + 0+1000+135435+116714+171295+217341   # staff
  + 0+0+1400+22450+64850+23399   # maintenance
  + 0+0+5674+1880+1200+11272    # cleaning
  + 0+0+0+3000+3500+3500        # waste
  + 0+3048+136960+18323+7662+7770  # shopping
  + 0+207021+286755+212229+1187771+53998  # furniture
  + 0+0+81273+35595+7620+27700   # marketing
  + 0+0+6948+99673+6000+6000    # govt
  + 0+0+0+149+0+0               # bank charges
  + 0+15987+2781+700+0+0        # other
  + 0+0+0+41899+18264+750       # partner reimb
)
maint = 781700
true_rev = gross - 1_741_550 - 375_261  # per monthly formula = 6,700,770
print(f"  Gross Inflows (bank):     {gross:>12,}")
print(f"  Less: Sec Deposits (net): {sec:>12,}  [TOTAL col only — net held at Mar end]")
print(f"  Deposits Refunded YTD:    {refund:>12,}  [reference]")
print(f"  True Rent Revenue:        {true_rev:>12,}")
print(f"  Total OPEX (no cash rent):{-opex_nocash:>12,}")
print(f"  EBITDA:                   {true_rev - opex_nocash:>12,}")
