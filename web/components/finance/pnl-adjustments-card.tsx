"use client";

import { useCallback, useEffect, useState } from "react";
import { getPnlAdjustments, savePnlAdjustments } from "@/lib/api";

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const FIELDS: { key: "cash_holding" | "rent_paid_cash" | "cash_expense"; label: string; hint: string }[] = [
  { key: "cash_holding",   label: "Cash holding (physical)",     hint: "Cash in hand at month close — balance-sheet line" },
  { key: "rent_paid_cash", label: "Rent paid in cash",           hint: "Property rent paid to landlords in cash — OPEX" },
  { key: "cash_expense",   label: "Cash expense (other)",        hint: "Other operating costs paid in cash — OPEX" },
];

export function PnlAdjustmentsCard() {
  const [month, setMonth] = useState(currentMonth());
  const [vals, setVals] = useState({ cash_holding: "", rent_paid_cash: "", cash_expense: "" });
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
      });
      setState("idle");
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not load");
      setState("error");
    }
  }, []);

  useEffect(() => { load(month); }, [month, load]);

  async function save() {
    setState("saving");
    setError("");
    try {
      await savePnlAdjustments({
        month,
        cash_holding:   parseFloat(vals.cash_holding)   || 0,
        rent_paid_cash: parseFloat(vals.rent_paid_cash) || 0,
        cash_expense:   parseFloat(vals.cash_expense)   || 0,
      });
      setState("saved");
      setTimeout(() => setState("idle"), 1600);
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
      setState("error");
    }
  }

  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide">
          P&amp;L · Manual cash figures
        </p>
        <input
          type="month"
          value={month}
          onChange={(e) => setMonth(e.target.value)}
          className="text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-2 py-1 text-ink outline-none focus:ring-1 focus:ring-brand-pink"
        />
      </div>

      <p className="text-[10px] text-ink-muted -mt-1">
        These three never appear in the bank statement — enter them so the month&apos;s P&amp;L matches reality.
      </p>

      {frozen ? (
        <div className="rounded-lg bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-[11px] text-ink-muted">
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
                  onChange={(e) => setVals((v) => ({ ...v, [f.key]: e.target.value }))}
                  onWheel={(e) => e.currentTarget.blur()}
                  placeholder="0"
                  disabled={state === "loading"}
                  className="w-full text-base font-bold rounded-lg bg-[#F6F5F0] border border-[#E0DDD8] pl-7 pr-3 py-2 text-ink outline-none focus:ring-2 focus:ring-brand-pink disabled:opacity-50"
                />
              </div>
              <p className="text-[10px] text-ink-muted mt-0.5">{f.hint}</p>
            </div>
          ))}

          {error && (
            <p className="text-[10px] text-status-warn text-center">Could not save — {error}</p>
          )}

          <button
            onClick={save}
            disabled={state === "saving" || state === "loading"}
            className="w-full rounded-pill bg-brand-pink py-2.5 text-sm font-bold text-white active:opacity-70 disabled:opacity-50"
          >
            {state === "saving" ? "Saving…" : state === "saved" ? "Saved ✓" : `Save ${month} figures`}
          </button>
        </>
      )}
    </div>
  );
}
