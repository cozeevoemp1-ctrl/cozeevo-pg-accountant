"use client"

/**
 * DateTimeSelect — day / month / year / hour / minute dropdowns.
 * value / onChange use "YYYY-MM-DDTHH:MM" strings (same as input[type=datetime-local]).
 */

import { DateSelect } from "./date-select"

const HOURS   = Array.from({ length: 24 }, (_, i) => i)
const MINUTES = [0, 15, 30, 45]

interface Props {
  value:    string           // "YYYY-MM-DDTHH:MM" or ""
  onChange: (v: string) => void
  disabled?: boolean
}

export function DateTimeSelect({ value, onChange, disabled }: Props) {
  const [datePart, timePart] = value ? value.split("T") : ["", ""]
  const [hStr, mStr] = timePart ? timePart.split(":") : ["", ""]
  const hour   = hStr ? parseInt(hStr) : -1
  const minute = mStr !== undefined && mStr !== "" ? parseInt(mStr) : -1

  function emitTime(h: number, m: number) {
    if (!datePart || h < 0 || m < 0) return
    onChange(`${datePart}T${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`)
  }

  function onDateChange(d: string) {
    if (!d) { onChange(""); return }
    const h = hour  >= 0 ? hour  : 0
    const m = minute >= 0 ? minute : 0
    onChange(`${d}T${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`)
  }

  const sel = "flex-1 h-[42px] rounded-lg border border-[#E0DDD8] bg-surface px-2 text-sm text-ink appearance-none focus:outline-none focus:border-brand-pink disabled:opacity-50"

  return (
    <div className="flex flex-col gap-2 mt-1">
      <DateSelect value={datePart} onChange={onDateChange} disabled={disabled} />
      <div className="flex gap-2">
        <div className="relative flex-1">
          <select
            value={hour >= 0 ? hour : ""}
            onChange={e => emitTime(parseInt(e.target.value), minute >= 0 ? minute : 0)}
            disabled={disabled}
            className={sel}
          >
            <option value="">HH</option>
            {HOURS.map(h => <option key={h} value={h}>{String(h).padStart(2, "0")}</option>)}
          </select>
        </div>
        <div className="relative flex-1">
          <select
            value={minute >= 0 ? minute : ""}
            onChange={e => emitTime(hour >= 0 ? hour : 0, parseInt(e.target.value))}
            disabled={disabled}
            className={sel}
          >
            <option value="">MM</option>
            {MINUTES.map(m => <option key={m} value={m}>{String(m).padStart(2, "0")}</option>)}
          </select>
        </div>
        <div className="flex-1" />
      </div>
    </div>
  )
}
