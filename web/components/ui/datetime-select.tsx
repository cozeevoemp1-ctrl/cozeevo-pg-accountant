"use client"

/**
 * DateTimeSelect — date row [ DD | MMM | YYYY ] + time row [ HH | MM ]
 * value / onChange use "YYYY-MM-DDTHH:MM" strings.
 */

import { DateSelect } from "./date-select"

const HOURS   = Array.from({ length: 24 }, (_, i) => i)
const MINUTES = [0, 15, 30, 45]

interface Props {
  value:    string   // "YYYY-MM-DDTHH:MM" or ""
  onChange: (v: string) => void
  disabled?: boolean
}

export function DateTimeSelect({ value, onChange, disabled }: Props) {
  const [datePart, timePart] = value ? value.split("T") : ["", ""]
  const [hStr, mStr] = timePart ? timePart.split(":") : ["", ""]
  const hour   = hStr !== undefined && hStr !== "" ? parseInt(hStr) : -1
  const minute = mStr !== undefined && mStr !== "" ? parseInt(mStr) : -1

  function onDateChange(d: string) {
    if (!d) { onChange(""); return }
    const h = hour   >= 0 ? hour   : 0
    const m = minute >= 0 ? minute : 0
    onChange(`${d}T${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}`)
  }

  function emitTime(h: number, m: number) {
    if (!datePart) return
    onChange(`${datePart}T${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}`)
  }

  const sel = "flex-1 h-full bg-transparent text-sm text-ink appearance-none focus:outline-none px-2 disabled:opacity-50"

  return (
    <div className="mt-1 flex flex-col gap-2">
      {/* Date row */}
      <DateSelect value={datePart} onChange={onDateChange} disabled={disabled} />

      {/* Time row — half width */}
      <div className="flex h-[42px] rounded-lg border border-[#E0DDD8] bg-surface overflow-hidden w-1/2">
        <select
          value={hour >= 0 ? hour : ""}
          onChange={e => emitTime(parseInt(e.target.value), minute >= 0 ? minute : 0)}
          disabled={disabled}
          className={sel}
        >
          <option value="">HH</option>
          {HOURS.map(h => (
            <option key={h} value={h}>
              {String(h).padStart(2,"0")} {h < 12 ? "am" : "pm"}
            </option>
          ))}
        </select>
        <span className="self-center text-[#E0DDD8]">|</span>
        <select
          value={minute >= 0 ? minute : ""}
          onChange={e => emitTime(hour >= 0 ? hour : 0, parseInt(e.target.value))}
          disabled={disabled}
          className={sel}
        >
          <option value="">MM</option>
          {MINUTES.map(m => <option key={m} value={m}>{String(m).padStart(2,"0")}</option>)}
        </select>
      </div>
    </div>
  )
}
