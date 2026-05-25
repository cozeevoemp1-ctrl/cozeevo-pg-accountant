"use client"

/**
 * DateTimePickerInput — Option 4
 * Single connected row: [ DD ▾ | MMM ▾ | YYYY ▾ | 10:30 am ▾ ]
 * value / onChange: "YYYY-MM-DDTHH:MM"
 */

import { useState } from "react"

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
const YEARS  = [2025, 2026]

function daysInMonth(month: number, year: number) {
  return new Date(year, month, 0).getDate()
}

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
  value:    string
  onChange: (v: string) => void
}

export function DateTimePickerInput({ value, onChange }: Props) {
  const [datePart, timePart] = value ? value.split("T") : ["",""]
  const parts = datePart ? datePart.split("-").map(Number) : [0,0,0]

  const [selY, setSelY] = useState(parts[0] || 0)
  const [selM, setSelM] = useState(parts[1] || 0)
  const [selD, setSelD] = useState(parts[2] || 0)
  const [selT, setSelT] = useState(timePart || "")

  const maxDay = (selY && selM) ? daysInMonth(selM, selY) : 31

  function emitAll(y: number, m: number, d: number, t: string) {
    if (!y || !m || !d) return
    const safe = Math.min(d, daysInMonth(m, y))
    const date  = `${y}-${String(m).padStart(2,"0")}-${String(safe).padStart(2,"0")}`
    onChange(`${date}T${t || "09:00"}`)
  }

  const sel = "h-full bg-transparent text-sm text-ink appearance-none focus:outline-none px-2 cursor-pointer"
  const div = <div className="self-stretch w-px bg-[#E0DDD8] flex-shrink-0" />

  return (
    <div className="mt-1 flex h-[46px] rounded-lg border border-[#E0DDD8] bg-surface overflow-hidden focus-within:border-brand-pink transition-colors">
      <select
        value={selD || ""}
        onChange={e => { const v = +e.target.value; setSelD(v); emitAll(selY, selM, v, selT) }}
        className={sel + " w-[56px]"}
      >
        <option value="">DD</option>
        {Array.from({length: maxDay}, (_,i) => i+1).map(n => (
          <option key={n} value={n}>{String(n).padStart(2,"0")}</option>
        ))}
      </select>
      {div}
      <select
        value={selM || ""}
        onChange={e => { const v = +e.target.value; setSelM(v); emitAll(selY, v, selD, selT) }}
        className={sel + " w-[60px]"}
      >
        <option value="">Mon</option>
        {MONTHS.map((name, i) => <option key={name} value={i+1}>{name}</option>)}
      </select>
      {div}
      <select
        value={selY || ""}
        onChange={e => { const v = +e.target.value; setSelY(v); emitAll(v, selM, selD, selT) }}
        className={sel + " w-[68px]"}
      >
        <option value="">Year</option>
        {YEARS.map(yr => <option key={yr} value={yr}>{yr}</option>)}
      </select>
      {div}
      <select
        value={selT}
        onChange={e => { const v = e.target.value; setSelT(v); emitAll(selY, selM, selD, v) }}
        className={sel + " flex-1 min-w-0"}
      >
        <option value="">Time</option>
        {TIME_SLOTS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
      </select>
    </div>
  )
}
