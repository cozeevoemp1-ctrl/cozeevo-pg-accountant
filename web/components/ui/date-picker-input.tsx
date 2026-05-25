"use client"

/**
 * DatePickerInput — Option 4
 * Single connected row: [ DD ▾ | MMM ▾ | YYYY ▾ ]
 * value / onChange: "YYYY-MM-DD"
 */

import { useState } from "react"

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
  const [selY, setSelY] = useState(parts[0] || 0)
  const [selM, setSelM] = useState(parts[1] || 0)
  const [selD, setSelD] = useState(parts[2] || 0)

  const maxDay = (selY && selM) ? daysInMonth(selM, selY) : 31

  function emit(y: number, m: number, d: number) {
    if (!y || !m || !d) return
    const safe = Math.min(d, daysInMonth(m, y))
    onChange(`${y}-${String(m).padStart(2,"0")}-${String(safe).padStart(2,"0")}`)
  }

  const sel = "h-full bg-transparent text-sm text-ink appearance-none focus:outline-none px-3 cursor-pointer"
  const divider = <div className="self-stretch w-px bg-[#E0DDD8] flex-shrink-0" />

  return (
    <div className="mt-1 flex h-[46px] rounded-lg border border-[#E0DDD8] bg-surface overflow-hidden focus-within:border-brand-pink transition-colors">
      <select
        value={selD || ""}
        onChange={e => { const v = +e.target.value; setSelD(v); emit(selY, selM, v) }}
        className={sel + " w-[64px]"}
      >
        <option value="">DD</option>
        {Array.from({length: maxDay}, (_,i) => i+1).map(n => (
          <option key={n} value={n}>{String(n).padStart(2,"0")}</option>
        ))}
      </select>
      {divider}
      <select
        value={selM || ""}
        onChange={e => { const v = +e.target.value; setSelM(v); emit(selY, v, selD) }}
        className={sel + " flex-1"}
      >
        <option value="">Month</option>
        {MONTHS.map((name, i) => <option key={name} value={i+1}>{name}</option>)}
      </select>
      {divider}
      <select
        value={selY || ""}
        onChange={e => { const v = +e.target.value; setSelY(v); emit(v, selM, selD) }}
        className={sel + " w-[76px]"}
      >
        <option value="">Year</option>
        {YEARS.map(yr => <option key={yr} value={yr}>{yr}</option>)}
      </select>
    </div>
  )
}
