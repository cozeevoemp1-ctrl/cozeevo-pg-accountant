"""
PG Fill Rate + Check-in / Check-out Charts — all 4 options.
Run: python scripts/pg_charts.py
Saves: data/reports/pg_charts_*.png
"""
import sys, io, os, warnings, requests
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np
from datetime import date
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
TOTAL_BEDS = 293

# ── Fetch data ────────────────────────────────────────────────────────────────
r = requests.get(f"{SUPABASE_URL}/rest/v1/tenancies", headers=HEADERS,
    params={"select": "checkin_date,checkout_date,expected_checkout,status,stay_type",
            "status": "neq.cancelled", "limit": "2000"})
rows = r.json()

# ── Build monthly series ──────────────────────────────────────────────────────
MONTHS = [
    (2025, 10, "Oct"), (2025, 11, "Nov"), (2025, 12, "Dec"),
    (2026,  1, "Jan"), (2026,  2, "Feb"), (2026,  3, "Mar"), (2026,  4, "Apr"),
]
MONTH_ENDS = {
    (2025,10): date(2025,10,31), (2025,11): date(2025,11,30),
    (2025,12): date(2025,12,31), (2026, 1): date(2026, 1,31),
    (2026, 2): date(2026, 2,28), (2026, 3): date(2026, 3,31),
    (2026, 4): date(2026, 4,30),
}

def parse(d):
    return date.fromisoformat(d) if d else None

checkins  = {k: 0 for k in MONTHS}
checkouts = {k: 0 for k in MONTHS}
occupied  = {}

for row in rows:
    ci = parse(row["checkin_date"])
    co = parse(row["checkout_date"]) or parse(row["expected_checkout"])
    status = row["status"]
    if status == "no_show":
        continue

    if ci:
        key = (ci.year, ci.month, next(m[2] for m in MONTHS if m[0]==ci.year and m[1]==ci.month) if any(m[0]==ci.year and m[1]==ci.month for m in MONTHS) else None)
        if key[2]:
            checkins[key] += 1

    if co and status == "exited":
        key = (co.year, co.month, next((m[2] for m in MONTHS if m[0]==co.year and m[1]==co.month), None))
        if key[2]:
            checkouts[key] += 1

for yr, mo, lbl in MONTHS:
    end = MONTH_ENDS[(yr, mo)]
    count = 0
    for row in rows:
        if row["status"] == "no_show":
            continue
        ci = parse(row["checkin_date"])
        co = parse(row["checkout_date"]) or parse(row["expected_checkout"])
        if ci and ci <= end:
            if row["status"] == "active":
                count += 1
            elif row["status"] == "exited":
                if co and co > end:
                    count += 1
                elif co is None:
                    pass  # unknown exit date — skip
    occupied[(yr, mo, lbl)] = count

labels    = [m[2] for m in MONTHS]
ci_vals   = [checkins[m] for m in MONTHS]
co_vals   = [checkouts[m] for m in MONTHS]
occ_vals  = [occupied[m] for m in MONTHS]
fill_rate = [round(o / TOTAL_BEDS * 100, 1) for o in occ_vals]
net_flow  = [c - x for c, x in zip(ci_vals, co_vals)]

print("Month    | Check-ins | Check-outs | Occupied | Fill%")
for i, (yr, mo, lbl) in enumerate(MONTHS):
    print(f"{lbl:8} | {ci_vals[i]:9} | {co_vals[i]:10} | {occ_vals[i]:8} | {fill_rate[i]}")

os.makedirs("data/reports", exist_ok=True)

PINK  = "#EF1F9C"
BLUE  = "#00AEED"
GREEN = "#27AE60"
RED   = "#E74C3C"
DARK  = "#1C2B3A"
LIGHT_GREY = "#F0F4F8"

x = np.arange(len(labels))
bar_w = 0.35

# ═══════════════════════════════════════════════════════════════════════════════
# CHART 1 — Grouped Bars (check-ins/outs) + Fill Rate line (right axis)
# ═══════════════════════════════════════════════════════════════════════════════
fig, ax1 = plt.subplots(figsize=(12, 6))
fig.patch.set_facecolor("white")
ax1.set_facecolor(LIGHT_GREY)

b1 = ax1.bar(x - bar_w/2, ci_vals, bar_w, label="Check-ins",  color=GREEN, alpha=0.85, zorder=3)
b2 = ax1.bar(x + bar_w/2, co_vals, bar_w, label="Check-outs", color=RED,   alpha=0.85, zorder=3)

ax2 = ax1.twinx()
ax2.plot(x, fill_rate, color=PINK, linewidth=2.5, marker="o", markersize=7, label="Fill Rate %", zorder=4)
for i, v in enumerate(fill_rate):
    ax2.annotate(f"{v}%", (x[i], v), textcoords="offset points", xytext=(0, 10),
                 ha="center", fontsize=9, color=PINK, fontweight="bold")

ax1.set_xlabel("Month", fontsize=11)
ax1.set_ylabel("Tenants", fontsize=11)
ax2.set_ylabel("Fill Rate %", fontsize=11, color=PINK)
ax2.set_ylim(0, 110)
ax2.tick_params(axis="y", labelcolor=PINK)
ax1.set_xticks(x); ax1.set_xticklabels(labels)
ax1.set_title("Option 1 — Check-ins / Check-outs + Fill Rate", fontsize=13, fontweight="bold", pad=12)
ax1.grid(axis="y", alpha=0.4, zorder=0)
handles = [b1, b2, mpatches.Patch(color=PINK, label=f"Fill Rate %")]
ax1.legend(handles=handles, loc="upper left")

for bar in b1:
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
             str(int(bar.get_height())), ha="center", va="bottom", fontsize=8, color=DARK)
for bar in b2:
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
             str(int(bar.get_height())), ha="center", va="bottom", fontsize=8, color=DARK)

plt.tight_layout()
plt.savefig("data/reports/pg_chart1_combo_bars.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved chart 1")

# ═══════════════════════════════════════════════════════════════════════════════
# CHART 2 — Stacked Area (occupied pool) + check-in/out as stem markers
# ═══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(12, 6))
fig.patch.set_facecolor("white")
ax.set_facecolor(LIGHT_GREY)

ax.fill_between(x, occ_vals, alpha=0.25, color=BLUE, zorder=2)
ax.plot(x, occ_vals, color=BLUE, linewidth=2.5, marker="o", markersize=8, label="Occupied Beds", zorder=4)
ax.axhline(TOTAL_BEDS, color=DARK, linestyle="--", linewidth=1.2, alpha=0.5, label=f"Total Beds ({TOTAL_BEDS})", zorder=3)

for i, v in enumerate(occ_vals):
    ax.annotate(f"{v}\n({fill_rate[i]}%)", (x[i], v), textcoords="offset points",
                xytext=(0, 12), ha="center", fontsize=8.5, color=BLUE, fontweight="bold")

ax2 = ax.twinx()
ax2.bar(x - bar_w/2, ci_vals, bar_w*0.8, alpha=0.5, color=GREEN, label="Check-ins",  zorder=3)
ax2.bar(x + bar_w/2, co_vals, bar_w*0.8, alpha=0.5, color=RED,   label="Check-outs", zorder=3)
ax2.set_ylabel("Monthly Activity", fontsize=10, color=DARK)
ax2.set_ylim(0, max(ci_vals + co_vals) * 3)

ax.set_xticks(x); ax.set_xticklabels(labels)
ax.set_ylabel("Occupied Beds", fontsize=11, color=BLUE)
ax.set_ylim(0, TOTAL_BEDS * 1.2)
ax.set_title("Option 2 — Occupied Pool (Area) + Monthly Activity", fontsize=13, fontweight="bold", pad=12)
ax.grid(axis="y", alpha=0.4, zorder=0)

handles = [
    mpatches.Patch(color=BLUE, label="Occupied Beds", alpha=0.6),
    mpatches.Patch(color=DARK, label=f"Total Beds ({TOTAL_BEDS})", alpha=0.4),
    mpatches.Patch(color=GREEN, label="Check-ins", alpha=0.6),
    mpatches.Patch(color=RED,   label="Check-outs", alpha=0.6),
]
ax.legend(handles=handles, loc="lower right")
plt.tight_layout()
plt.savefig("data/reports/pg_chart2_area.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved chart 2")

# ═══════════════════════════════════════════════════════════════════════════════
# CHART 3 — Waterfall (net flow) + cumulative occupied line
# ═══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(12, 6))
fig.patch.set_facecolor("white")
ax.set_facecolor(LIGHT_GREY)

bar_colors = [GREEN if n >= 0 else RED for n in net_flow]
bars = ax.bar(x, net_flow, color=bar_colors, alpha=0.85, width=0.5, zorder=3)
ax.axhline(0, color=DARK, linewidth=0.8, zorder=2)

for bar, val in zip(bars, net_flow):
    offset = 1 if val >= 0 else -3
    ax.text(bar.get_x() + bar.get_width()/2, val + offset,
            f"+{val}" if val > 0 else str(val),
            ha="center", va="bottom" if val >= 0 else "top",
            fontsize=9, fontweight="bold",
            color=GREEN if val >= 0 else RED)

ax2 = ax.twinx()
ax2.plot(x, occ_vals, color=BLUE, linewidth=2.5, marker="D", markersize=7, label="Occupied Beds", zorder=4)
ax2.plot(x, fill_rate, color=PINK, linewidth=1.8, marker="s", markersize=6,
         linestyle="--", label="Fill Rate %", zorder=4)
for i, (o, f) in enumerate(zip(occ_vals, fill_rate)):
    ax2.annotate(f"{f}%", (x[i], f), textcoords="offset points",
                 xytext=(6, 0), fontsize=8, color=PINK)

ax.set_xticks(x); ax.set_xticklabels(labels)
ax.set_ylabel("Net Tenant Change (check-ins − check-outs)", fontsize=10)
ax2.set_ylabel("Beds / Fill Rate", fontsize=10)
ax2.set_ylim(0, TOTAL_BEDS * 1.2)
ax.set_title("Option 3 — Net Flow Waterfall + Occupancy Trend", fontsize=13, fontweight="bold", pad=12)
ax.grid(axis="y", alpha=0.4, zorder=0)
ax2.legend(loc="lower right")
plt.tight_layout()
plt.savefig("data/reports/pg_chart3_waterfall.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved chart 3")

# ═══════════════════════════════════════════════════════════════════════════════
# CHART 4 — Three-panel dashboard
# ═══════════════════════════════════════════════════════════════════════════════
fig, (ax_top, ax_mid, ax_bot) = plt.subplots(3, 1, figsize=(12, 10),
    gridspec_kw={"height_ratios": [3, 2, 1]})
fig.patch.set_facecolor("white")
fig.suptitle("Option 4 — Dashboard View: Fill Rate + Activity + Net Flow",
             fontsize=13, fontweight="bold", y=0.98)

# Panel 1: Fill Rate area
ax_top.set_facecolor(LIGHT_GREY)
ax_top.fill_between(x, fill_rate, alpha=0.3, color=PINK)
ax_top.plot(x, fill_rate, color=PINK, linewidth=3, marker="o", markersize=9)
for i, v in enumerate(fill_rate):
    ax_top.annotate(f"{v}%\n({occ_vals[i]} beds)", (x[i], v),
                    textcoords="offset points", xytext=(0, 12),
                    ha="center", fontsize=9, color=DARK, fontweight="bold")
ax_top.set_ylim(0, 110)
ax_top.set_ylabel("Fill Rate %", fontsize=10)
ax_top.axhline(100, color=DARK, linestyle=":", alpha=0.4)
ax_top.set_xticks(x); ax_top.set_xticklabels([])
ax_top.grid(axis="y", alpha=0.4)
ax_top.set_title("Fill Rate %", fontsize=10, loc="left", pad=4)

# Panel 2: Mirrored check-in/out bars
ax_mid.set_facecolor(LIGHT_GREY)
ax_mid.bar(x, ci_vals,  color=GREEN, alpha=0.8, label="Check-ins")
ax_mid.bar(x, [-v for v in co_vals], color=RED, alpha=0.8, label="Check-outs (below zero)")
ax_mid.axhline(0, color=DARK, linewidth=0.8)
for i, (ci, co) in enumerate(zip(ci_vals, co_vals)):
    if ci > 0: ax_mid.text(x[i], ci + 0.5, str(ci), ha="center", fontsize=8, color=GREEN, fontweight="bold")
    if co > 0: ax_mid.text(x[i], -co - 0.5, str(co), ha="center", va="top", fontsize=8, color=RED, fontweight="bold")
ax_mid.set_ylabel("Tenants", fontsize=10)
ax_mid.set_xticks(x); ax_mid.set_xticklabels([])
ax_mid.grid(axis="y", alpha=0.4)
ax_mid.legend(loc="upper left", fontsize=9)
ax_mid.set_title("Monthly Check-ins (above) vs Check-outs (below)", fontsize=10, loc="left", pad=4)

# Panel 3: Net change dots
ax_bot.set_facecolor(LIGHT_GREY)
net_colors = [GREEN if n >= 0 else RED for n in net_flow]
ax_bot.bar(x, net_flow, color=net_colors, alpha=0.85, width=0.5)
ax_bot.axhline(0, color=DARK, linewidth=0.8)
for i, v in enumerate(net_flow):
    ax_bot.text(x[i], v + (0.5 if v >= 0 else -0.5), f"+{v}" if v > 0 else str(v),
                ha="center", va="bottom" if v >= 0 else "top", fontsize=8, fontweight="bold",
                color=GREEN if v >= 0 else RED)
ax_bot.set_ylabel("Net", fontsize=9)
ax_bot.set_xticks(x); ax_bot.set_xticklabels(labels, fontsize=10)
ax_bot.set_title("Net Change per Month", fontsize=10, loc="left", pad=4)
ax_bot.grid(axis="y", alpha=0.4)

plt.tight_layout()
plt.savefig("data/reports/pg_chart4_dashboard.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved chart 4")
print("All done — data/reports/pg_chart*.png")
