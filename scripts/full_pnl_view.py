"""Quick full P&L view: Income vs Operating vs Investment vs Non-Operating."""
import pandas as pd
from scripts.pnl_report import classify, EXPENSE_RULES, INCOME_RULES

SRC1 = "2025 statement.xlsx"
SRC2 = "data/exports/Statement-124563400000961-03-10-2026-20-15-08 (1)_extracted.xlsx"
MONTHS = ["Oct 2025", "Nov 2025", "Dec 2025", "Jan 2026", "Feb 2026", "Mar 2026"]

frames = []
for src in [SRC1, SRC2]:
    try:
        d = pd.read_excel(src)
        d["Withdrawals"] = d["Withdrawals"].apply(lambda x: x if isinstance(x, (int, float)) and pd.notna(x) else 0)
        d["Deposits"] = d["Deposits"].apply(lambda x: x if isinstance(x, (int, float)) and pd.notna(x) else 0)
        d["_date"] = pd.to_datetime(d["Transaction Date"], format="%Y-%m-%d", errors="coerce")
        frames.append(d)
        print(f"Loaded {src}: {len(d)} rows, {d['_date'].min().date()} to {d['_date'].max().date()}")
    except Exception as e:
        print(f"Error loading {src}: {e}")

df = pd.concat(frames, ignore_index=True)
before = len(df)
df = df.drop_duplicates(subset=["_date", "Description", "Withdrawals", "Deposits"])
print(f"Combined: {before} -> {len(df)} rows after dedup")
df["Month"] = pd.Categorical(df["_date"].dt.strftime("%b %Y"), categories=MONTHS, ordered=True)

# Classify
exp_df = df[df["Withdrawals"] > 0].copy()
exp_df[["Cat", "Sub"]] = pd.DataFrame(
    [classify(d, EXPENSE_RULES) for d in exp_df["Description"]], index=exp_df.index
)
exp_df = exp_df[exp_df["Cat"] != "_income_"]

inc_df = df[df["Deposits"] > 0].copy()
inc_df[["Cat", "Sub"]] = pd.DataFrame(
    [classify(d, INCOME_RULES) for d in inc_df["Description"]], index=inc_df.index
)

INVESTMENT = ["Furniture & Fittings"]
NON_OP = ["Non-Operating"]
W = 12


def fmt(v):
    return f"{v:>{W},.0f}" if v else f"{'-':>{W}}"


def print_pivot(data, idx_col, val_col, label):
    pivot = data.pivot_table(index=idx_col, columns="Month", values=val_col, aggfunc="sum", fill_value=0, observed=True)
    for m in MONTHS:
        if m not in pivot.columns:
            pivot[m] = 0
    pivot = pivot[MONTHS]
    pivot["TOTAL"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("TOTAL", ascending=False)
    for cat, row in pivot.iterrows():
        line = f"  {str(cat):<32}" + "".join(fmt(row.get(m, 0)) for m in MONTHS) + f"{row['TOTAL']:>14,.0f}"
        print(line)
    totals = {m: data[data["Month"] == m][val_col].sum() for m in MONTHS}
    totals["TOTAL"] = sum(totals.values())
    line = f"  {'TOTAL ' + label:<32}" + "".join(fmt(totals[m]) for m in MONTHS) + f"{totals['TOTAL']:>14,.0f}"
    print(line)
    return totals


header = f"  {'':32}" + "".join(f"{m:>{W}}" for m in MONTHS) + f"{'TOTAL':>14}"
sep = "=" * len(header)

print(f"\n{sep}")
print("INCOME")
print(header)
print("-" * len(header))
inc_totals = print_pivot(inc_df, "Cat", "Deposits", "INCOME")

print(f"\nOPERATING EXPENSES")
print("-" * len(header))
op_exp = exp_df[~exp_df["Cat"].isin(INVESTMENT + NON_OP)]
op_totals = print_pivot(op_exp, "Cat", "Withdrawals", "OPERATING")

print(f"\nINVESTMENT (CAPEX)")
print("-" * len(header))
inv_exp = exp_df[exp_df["Cat"].isin(INVESTMENT)]
inv_totals = print_pivot(inv_exp, "Sub", "Withdrawals", "INVESTMENT")

print(f"\nNON-OPERATING")
print("-" * len(header))
no_exp = exp_df[exp_df["Cat"].isin(NON_OP)]
no_totals = print_pivot(no_exp, "Sub", "Withdrawals", "NON-OPERATING")

# Summary
print(f"\n{sep}")
print("SUMMARY")
print(header)
print("-" * len(header))

for label, totals in [
    ("A. Income", inc_totals),
    ("B. Operating Expenses", op_totals),
    ("C. Investment (CAPEX)", inv_totals),
    ("D. Non-Operating", no_totals),
]:
    line = f"  {label:<32}" + "".join(fmt(totals[m]) for m in MONTHS) + f"{totals['TOTAL']:>14,.0f}"
    print(line)

print("-" * len(header))

op_profit = {m: inc_totals[m] - op_totals[m] for m in MONTHS}
op_profit["TOTAL"] = inc_totals["TOTAL"] - op_totals["TOTAL"]
line = f"  {'Operating Profit (A-B)':<32}" + "".join(fmt(op_profit[m]) for m in MONTHS) + f"{op_profit['TOTAL']:>14,.0f}"
print(line)

total_out = {m: op_totals[m] + inv_totals[m] + no_totals[m] for m in MONTHS}
total_out["TOTAL"] = op_totals["TOTAL"] + inv_totals["TOTAL"] + no_totals["TOTAL"]
line = f"  {'Total Outflow (B+C+D)':<32}" + "".join(fmt(total_out[m]) for m in MONTHS) + f"{total_out['TOTAL']:>14,.0f}"
print(line)

net = {m: inc_totals[m] - total_out[m] for m in MONTHS}
net["TOTAL"] = inc_totals["TOTAL"] - total_out["TOTAL"]
line = f"  {'Net Cash (A-B-C-D)':<32}" + "".join(fmt(net[m]) for m in MONTHS) + f"{net['TOTAL']:>14,.0f}"
print(line)
print(sep)
