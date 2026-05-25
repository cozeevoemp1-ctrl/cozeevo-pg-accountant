"use client"

/**
 * DateTimePickerInput — Option 4
 * Single connected row: [ DD ▾ | MMM ▾ | YYYY ▾ | 10:30 am ▾ ]
 * value / onChange: "YYYY-MM-DDTHH:MM"
 */

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
const YEARS  = [2025, 2026]

function daysInMonth(month: number, year: number) {
  return new Date(year, month, 0).getDate()
}

// 12:00 am → 11:45 pm, every 15 min
const TIME_SLOTS: { label: string; value: string }[] = []
for (let h = 0; h < 24; h++) {
  for (const min of [0, 15, 30, 45]) {
    const period = h < 12 ? "am" : "pm"
    const h12    = h === 0 ? 12 : h > 12 ? h - 12 : h
    TIME_SLOTS.push({
      label: `${h12}:${String(min).padStart(2,"0")} ${period}`,
      value: `${String(h).padStart(2,"0")}:${String(min).padStart(2,"0")}`,
    })
  }
}

interface Props {
  value:    string   // "YYYY-MM-DDTHH:MM" or ""
  onChange: (v: string) => void
}

export function DateTimePickerInput({ value, onChange }: Props) {
  const [datePart, timePart] = value ? value.split("T") : ["",""]
  const parts = datePart ? datePart.split("-").map(Number) : [0,0,0]
  const y = parts[0], m = parts[1], d = parts[2]
  const maxDay = (y && m) ? daysInMonth(m, y) : 31

  // Round timePart to nearest 15-min slot value for matching
  const timeVal = timePart
    ? (() => {
        const [hh, mm] = timePart.split(":").map(Number)
        const rounded  = Math.round(mm / 15) * 15
        const finalMin = rounded === 60 ? 0 : rounded
        const finalHr  = rounded === 60 ? hh + 1 : hh
        return `${String(finalHr % 24).padStart(2,"0")}:${String(finalMin).padStart(2,"0")}`
      })()
    : ""

  function emitDate(year: number, month: number, day: number) {
    if (!year || !month || !day) return
    const safe = Math.min(day, daysInMonth(month, year))
    const date  = `${year}-${String(month).padStart(2,"0")}-${String(safe).padStart(2,"0")}`
    onChange(timePart ? `${date}T${timePart}` : `${date}T09:00`)
  }

  function emitTime(tv: string) {
    const date = datePart || `${new Date().getFullYear()}-${String(new Date().getMonth()+1).padStart(2,"0")}-${String(new Date().getDate()).padStart(2,"0")}`
    onChange(`${date}T${tv}`)
  }

  const sel = "h-full bg-transparent text-sm text-ink appearance-none focus:outline-none px-2 cursor-pointer"
  const div = <div className="self-stretch w-px bg-[#E0DDD8] flex-shrink-0" />

  return (
    <div className="mt-1 flex h-[46px] rounded-lg border border-[#E0DDD8] bg-surface overflow-hidden focus-within:border-brand-pink transition-colors">
      <select value={d || ""} onChange={e => emitDate(y, m, +e.target.value)} className={sel + " w-[56px]"}>
        <option value="">DD</option>
        {Array.from({length: maxDay}, (_,i) => i+1).map(n => (
          <option key={n} value={n}>{String(n).padStart(2,"0")}</option>
        ))}
      </select>
      {div}
      <select value={m || ""} onChange={e => emitDate(y, +e.target.value, d)} className={sel + " w-[62px]"}>
        <option value="">Mon</option>
        {MONTHS.map((name, i) => <option key={name} value={i+1}>{name}</option>)}
      </select>
      {div}
      <select value={y || ""} onChange={e => emitDate(+e.target.value, m, d)} className={sel + " w-[68px]"}>
        <option value="">Year</option>
        {YEARS.map(yr => <option key={yr} value={yr}>{yr}</option>)}
      </select>
      {div}
      <select value={timeVal} onChange={e => emitTime(e.target.value)} className={sel + " flex-1"}>
        <option value="">Time</option>
        {TIME_SLOTS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
      </select>
    </div>
  )
}
