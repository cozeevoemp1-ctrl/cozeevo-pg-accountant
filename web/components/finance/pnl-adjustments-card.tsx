"use client";

import { useCallback, useEffect, useState } from "react";
import { getPnlAdjustments, savePnlAdjustments } from "@/lib/api";
import { rupee } from "@/lib/format";
import { addMonths, periodMonth } from "@/lib/date";

type AdjKey = "cash_holding" | "rent_paid_cash" | "cash_expense" | "offline_cash";
const FIELDS: { key: AdjKey; label: string; hint: string }[] = [
  { key: "cash_holding",   label: "Cash holding (physical)",     hint: "Cash in hand at month close — balance-sheet line" },
  { key: "rent_paid_cash", label: "Rent paid in cash",           hint: "Property rent paid to landlords in cash — OPEX" },
  { key: "cash_expense",   label: "Cash expense (other)",        hint: "Other operating costs paid in cash — OPEX" },
  { key: "offline_cash",   label: "Cash collected, not in app",  hint: "Cash received this month that was never entered in the app — added to the cash income line" },
];
const EMPTY = { cash_holding: "", rent_paid_cash: "", cash_expense: "", offline_cash: "" };
const ZERO  = { cash_holding: 0,  rent_paid_cash: 0,  cash_expense: 0,  offline_cash: 0 };

export function PnlAdjustmentsCard({ onSaved }: { onSaved?: (month: string) => void } = {}) {
  // Default = PREVIOUS month: these figures are entered at month close, and on
  // the 1st the current month has nothing to close (Kiran keyed August into
  // September on 2026-09-01). The picker still switches to any month.
  const [month, setMonth] = useState(addMonths(periodMonth(), -1));
  const [vals, setVals] = useState<Record<AdjKey, string>>(EMPTY);
  // Values as loaded from the server — used to detect overwrites of saved figures
  const [saved, setSaved] = useState<Record<AdjKey, number>>(ZERO);
  const [overwriteWarning, setOverwriteWarning] = useState<string[] | null>(null);
  const [frozen, setFrozen] = useState(false);
  const [state, setState] = useState<"idle" | "loading" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState("");

  const load = useCallback(async (m: string) => {
    setState("loading");
    setError("");
    try {
      const a = await getPnlAdjustments(m);
      setFrozen(a.is_verified_frozen);
      setVals({
        cash_holding:   a.cash_holding   ? String(a.cash_holding)   : "",
        rent_paid_cash: a.rent_paid_cash ? String(a.rent_paid_cash) : "",
        cash_expense:   a.cash_expense   ? String(a.cash_expense)   : "",
        offline_cash:   a.offline_cash   ? String(a.offline_cash)   : "",
      });
      setSaved({
        cash_holding:   a.cash_holding   || 0,
        rent_paid_cash: a.rent_paid_cash || 0,
        cash_expense:   a.cash_expense   || 0,
        offline_cash:   a.offline_cash   || 0,
      });
      setOverwriteWarning(null);
      setState("idle");
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not load");
      setState("error");
    }
  }, []);

  useEffect(() => { load(month); }, [month, load]);

  async function save() {
    // Overwrite guardrail: changing an already-saved non-zero figure needs a
    // second tap (a test save once clobbered July's closed rent figure).
    if (!overwriteWarning) {
      const diffs = FIELDS
        .filter((f) => saved[f.key] > 0 && (parseFloat(vals[f.key]) || 0) !== saved[f.key])
        .map((f) => `${f.label}: ${rupee(saved[f.key])} → ${rupee(parseFloat(vals[f.key]) || 0)}`);
      if (diffs.length > 0) {
        setOverwriteWarning(diffs);
        return;
      }
    }
    setOverwriteWarning(null);
    setState("saving");
    setError("");
    try {
      await savePnlAdjustments({
        month,
        cash_holding:   parseFloat(vals.cash_holding)   || 0,
        rent_paid_cash: parseFloat(vals.rent_paid_cash) || 0,
        cash_expense:   parseFloat(vals.cash_expense)   || 0,
        offline_cash:   parseFloat(vals.offline_cash)   || 0,
      });
      setState("saved");
      // The P&L is computed live server-side — telling the page the month is
      // enough to "recalculate": the P&L card jumps there and refetches.
      onSaved?.(month);
      setTimeout(() => setState("idle"), 1600);
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
      setState("error");
    }
  }

  return (
    <div className="bg-surface rounded-card border border-border px-4 py-3 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide">
          P&amp;L · Manual cash figures
        </p>
        <input
          type="month"
          value={month}
          onChange={(e) => setMonth(e.target.value)}
          className="text-xs rounded-pill bg-bg border border-border-strong px-2 py-1 text-ink outline-none focus:ring-1 focus:ring-brand-pink"
        />
      </div>

      <p className="text-[10px] text-ink-muted -mt-1">
        These figures never appear in the bank statement — enter them so the month&apos;s P&amp;L matches reality.
      </p>

      {frozen ? (
        <div className="rounded-lg bg-bg border border-border-strong px-3 py-2 text-[11px] text-ink-muted">
          {month} is a verified frozen month — its figures are locked in the report.
        </div>
      ) : (
        <>
          {FIELDS.map((f) => (
            <div key={f.key}>
              <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">
                {f.label}
              </label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted text-sm">₹</span>
                <input
                  type="number" inputMode="numeric" min="0"
                  value={vals[f.key]}
                  onChange={(e) => { setOverwriteWarning(null); setVals((v) => ({ ...v, [f.key]: e.target.value })); }}
                  onWheel={(e) => e.currentTarget.blur()}
                  placeholder="0"
                  disabled={state === "loading"}
                  className="w-full text-base font-bold rounded-lg bg-bg border border-border-strong pl-7 pr-3 py-2 text-ink outline-none focus:ring-2 focus:ring-brand-pink disabled:opacity-50"
                />
              </div>
              <p className="text-[10px] text-ink-muted mt-0.5">{f.hint}</p>
            </div>
          ))}

          {error && (
            <p className="text-[10px] text-status-warn text-center">Could not save — {error}</p>
          )}

          {overwriteWarning && (
            <div className="rounded-lg bg-[#FFF5F0] border border-status-warn px-3 py-2 flex flex-col gap-1">
              <p className="text-[11px] font-bold text-status-warn">
                This month already has saved figures — you are changing:
              </p>
              {overwriteWarning.map((d) => (
                <p key={d} className="text-[11px] text-status-warn">{d}</p>
              ))}
              <button
                onClick={() => setOverwriteWarning(null)}
                className="self-end text-[10px] font-bold text-ink-muted underline"
              >
                Cancel
              </button>
            </div>
          )}

          <button
            onClick={save}
            disabled={state === "saving" || state === "loading"}
            className="w-full rounded-pill bg-brand-pink py-2.5 text-sm font-bold text-white active:opacity-70 disabled:opacity-50"
          >
            {state === "saving" ? "Saving…"
              : state === "saved" ? "Saved ✓"
              : overwriteWarning ? "Confirm overwrite"
              : `Save ${month} figures`}
          </button>
        </>
      )}
    </div>
  );
}
