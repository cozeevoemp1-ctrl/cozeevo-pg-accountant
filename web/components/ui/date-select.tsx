"use client"

/**
 * DateSelect — day / month / year dropdowns.
 * value / onChange use "YYYY-MM-DD" strings (same as input[type=date]).
 * Drops the native date picker entirely so year is a simple select.
 */

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

function yearRange(): number[] {
  const y = new Date().getFullYear()
  return [y - 1, y]
}

function daysInMonth(month: number, year: number): number {
  return new Date(year, month, 0).getDate()
}

interface Props {
  value:    string           // "YYYY-MM-DD" or ""
  onChange: (v: string) => void
  disabled?: boolean
}

export function DateSelect({ value, onChange, disabled }: Props) {
  const parts  = value ? value.split("-") : ["", "", ""]
  const year   = parseInt(parts[0]) || 0
  const month  = parseInt(parts[1]) || 0
  const day    = parseInt(parts[2]) || 0
  const years  = yearRange()
  const maxDay = year && month ? daysInMonth(month, year) : 31

  function emit(y: number, m: number, d: number) {
    if (!y || !m || !d) { onChange(""); return }
    const safeDay = Math.min(d, daysInMonth(m, y))
    onChange(`${y}-${String(m).padStart(2, "0")}-${String(safeDay).padStart(2, "0")}`)
  }

  const sel = "flex-1 h-[42px] rounded-lg border border-[#E0DDD8] bg-surface px-2 text-sm text-ink appearance-none focus:outline-none focus:border-brand-pink disabled:opacity-50"

  return (
    <div className="flex gap-2 mt-1">
      <div className="relative flex-1">
        <select value={day || ""} onChange={e => emit(year, month, parseInt(e.target.value))} disabled={disabled} className={sel}>
          <option value="">DD</option>
          {Array.from({ length: maxDay }, (_, i) => i + 1).map(d => (
            <option key={d} value={d}>{String(d).padStart(2, "0")}</option>
          ))}
        </select>
      </div>
      <div className="relative flex-1">
        <select value={month || ""} onChange={e => emit(year, parseInt(e.target.value), day)} disabled={disabled} className={sel}>
          <option value="">MMM</option>
          {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
        </select>
      </div>
      <div className="relative w-[88px]">
        <select value={year || ""} onChange={e => emit(parseInt(e.target.value), month, day)} disabled={disabled} className={sel + " w-full"}>
          <option value="">YYYY</option>
          {years.map(y => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>
    </div>
  )
}
