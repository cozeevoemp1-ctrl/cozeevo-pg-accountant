"use client"

/** THE month picker header: ← Jan 2026 →. Value is "YYYY-MM". */
import { addMonths, monthLabel } from "@/lib/date"

export function MonthNav({
  value,
  onChange,
  maxMonth,
  dark = false,
}: {
  value: string
  onChange: (ym: string) => void
  /** optional "YYYY-MM" upper bound (e.g. current month) */
  maxMonth?: string
  /** finance dark theme */
  dark?: boolean
}) {
  const atMax = maxMonth !== undefined && value >= maxMonth
  const btn = dark
    ? "w-8 h-8 rounded-full bg-white/10 text-white/80 disabled:opacity-30"
    : "w-8 h-8 rounded-full bg-bg text-ink disabled:opacity-30"
  const label = dark ? "text-white/90" : "text-ink"
  return (
    <div className="flex items-center justify-center gap-4">
      <button className={btn} onClick={() => onChange(addMonths(value, -1))} aria-label="Previous month">
        ‹
      </button>
      <span className={`text-sm font-semibold min-w-[92px] text-center ${label}`}>{monthLabel(value)}</span>
      <button className={btn} onClick={() => onChange(addMonths(value, 1))} disabled={atMax} aria-label="Next month">
        ›
      </button>
    </div>
  )
}
