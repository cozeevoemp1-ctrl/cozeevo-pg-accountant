"""List remaining Other Expenses transactions (uses live rules from pnl_report)."""
import sys
sys.path.insert(0, '.')
import pandas as pd
from scripts.pnl_report import EXPENSE_RULES, SRC, MONTHS

def classify(desc, rules):
    d = (desc or "").lower()
    for cat, sub, keywords in rules:
        if not keywords:
            continue
        for kw in keywords:
            if kw in d:
                return cat, sub
    return rules[-1][0], rules[-1][1]

df = pd.read_excel(SRC)
df["Withdrawals"] = df["Withdrawals"].apply(lambda x: x if isinstance(x, float) else 0)
df["_date"] = pd.to_datetime(df["Transaction Date"], format="%Y-%m-%d", errors="coerce")
df["Month"] = df["_date"].dt.strftime("%b %Y")
exp_df = df[df["Withdrawals"] > 0].copy()
exp_df[["Cat","Sub"]] = pd.DataFrame(
    [classify(d, EXPENSE_RULES) for d in exp_df["Description"]], index=exp_df.index)

others = exp_df[exp_df["Cat"] == "Other Expenses"].sort_values("Withdrawals", ascending=False)
print(f"Remaining Other Expenses: {len(others)} rows, Rs {others['Withdrawals'].sum():,.0f}")
print()
for _, r in others.iterrows():
    print(f"{r['Transaction Date']}  Rs {r['Withdrawals']:>8,.0f}  {str(r['Description'])[:80]}")
