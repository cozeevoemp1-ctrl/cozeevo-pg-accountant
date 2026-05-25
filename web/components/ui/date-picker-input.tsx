"use client"

/**
 * DatePickerInput — Option 4
 * Single connected row: [ DD ▾ | MMM ▾ | YYYY ▾ ]
 * value / onChange: "YYYY-MM-DD"
 */

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
const YEARS  = [2025, 2026]

function daysInMonth(month: number, year: number) {
  return new Date(year, month, 0).getDate()
}

interface Props {
  value:    string
  onChange: (v: string) => void
}

export function DatePickerInput({ value, onChange }: Props) {
  const parts = value ? value.split("-").map(Number) : [0, 0, 0]
  const y = parts[0], m = parts[1], d = parts[2]
  const maxDay = (y && m) ? daysInMonth(m, y) : 31

  function emit(year: number, month: number, day: number) {
    if (!year || !month || !day) return
    const safe = Math.min(day, daysInMonth(month, year))
    onChange(`${year}-${String(month).padStart(2,"0")}-${String(safe).padStart(2,"0")}`)
  }

  const sel = "h-full bg-transparent text-sm text-ink appearance-none focus:outline-none px-3 cursor-pointer"
  const div = <div className="self-stretch w-px bg-[#E0DDD8] flex-shrink-0" />

  return (
    <div className="mt-1 flex h-[46px] rounded-lg border border-[#E0DDD8] bg-surface overflow-hidden focus-within:border-brand-pink transition-colors">
      <select value={d || ""} onChange={e => emit(y, m, +e.target.value)} className={sel + " w-[64px]"}>
        <option value="">DD</option>
        {Array.from({length: maxDay}, (_,i) => i+1).map(n => (
          <option key={n} value={n}>{String(n).padStart(2,"0")}</option>
        ))}
      </select>
      {div}
      <select value={m || ""} onChange={e => emit(y, +e.target.value, d)} className={sel + " flex-1"}>
        <option value="">Month</option>
        {MONTHS.map((name, i) => <option key={name} value={i+1}>{name}</option>)}
      </select>
      {div}
      <select value={y || ""} onChange={e => emit(+e.target.value, m, d)} className={sel + " w-[76px]"}>
        <option value="">Year</option>
        {YEARS.map(yr => <option key={yr} value={yr}>{yr}</option>)}
      </select>
    </div>
  )
}
