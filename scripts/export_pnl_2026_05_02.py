"""
Regenerate the canonical P&L Excel locally.
Output: data/reports/PnL_Accrual_2026_05_03.xlsx

Uses the same builder as the PWA download endpoint (/finance/pnl/excel)
so local script and app produce identical files.

Run:
  venv/Scripts/python scripts/export_pnl_2026_05_02.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reports.pnl_builder import build_pnl_workbook

OUT = Path(__file__).parent.parent / "data" / "reports" / "PnL_Accrual_2026_05_03.xlsx"

if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    build_pnl_workbook().save(OUT)
    print(f"Saved: {OUT}")
