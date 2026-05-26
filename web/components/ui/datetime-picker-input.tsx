"use client"

/**
 * DateTimePickerInput
 * - Tap date row → inline calendar popup
 * - Tap year in popup header → year grid for fast selection
 * - Time: HH MM inputs + AM/PM toggle (12-hr display, stored as 24-hr internally)
 * value / onChange: "YYYY-MM-DDTHH:MM" (24-hr)
 */

import { useState, useRef, useEffect } from "react"

const MONTHS_SHORT = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
const DAYS_OF_WEEK = ["Su","Mo","Tu","We","Th","Fr","Sa"]

function daysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate()
}
function firstDayOfMonth(year: number, month: number) {
  return new Date(year, month, 1).getDay()
}

// "14:30" → { h12: 2, min: 30, period: "PM" }
function parse24(t: string) {
  if (!t) return { h12: 12, min: 0, period: "AM" as const }
  const [hh, mm] = t.split(":").map(Number)
  const period = hh < 12 ? "AM" as const : "PM" as const
  const h12 = hh === 0 ? 12 : hh > 12 ? hh - 12 : hh
  return { h12, min: mm ?? 0, period }
}

// { h12, min, period } → "14:30"
function to24(h12: number, min: number, period: "AM" | "PM") {
  let h = h12 % 12
  if (period === "PM") h += 12
  return `${String(h).padStart(2,"0")}:${String(min).padStart(2,"0")}`
}

interface Props {
  value:    string
  onChange: (v: string) => void
}

export function DateTimePickerInput({ value, onChange }: Props) {
  const today = new Date()

  const [datePart, timePart0] = value ? value.split("T") : ["", ""]
  const { h12: initH, min: initMin, period: initPeriod } = parse24(timePart0 || "")

  const [selYear,  setSelYear]  = useState(() => datePart ? +datePart.split("-")[0] : today.getFullYear())
  const [selMonth, setSelMonth] = useState(() => datePart ? +datePart.split("-")[1] - 1 : today.getMonth())
  const [selDay,   setSelDay]   = useState(() => datePart ? +datePart.split("-")[2] : 0)

  const [hour,   setHour]   = useState(timePart0 ? String(initH) : "")
  const [minute, setMinute] = useState(timePart0 ? String(initMin).padStart(2,"0") : "")
  const [period, setPeriod] = useState<"AM"|"PM">(initPeriod)

  const [open,      setOpen]     = useState(false)
  const [yearMode,  setYearMode] = useState(false)
  const [viewYear,  setViewYear] = useState(selYear)
  const [viewMonth, setViewMonth] = useState(selMonth)

  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  function emitDate(y: number, m: number, d: number, h: string, min: string, p: "AM"|"PM") {
    if (!d) return  // only date is required; time defaults to 12:00 if not yet entered
    const ds = `${y}-${String(m+1).padStart(2,"0")}-${String(d).padStart(2,"0")}`
    const ts = to24(+h || 12, +min || 0, p)
    onChange(`${ds}T${ts}`)
  }

  function pickDay(d: number) {
    setSelYear(viewYear); setSelMonth(viewMonth); setSelDay(d)
    emitDate(viewYear, viewMonth, d, hour, minute, period)
    setOpen(false)
  }

  function pickYear(y: number) { setViewYear(y); setYearMode(false) }

  function prevMonth() {
    if (viewMonth === 0) { setViewYear(v => v-1); setViewMonth(11) }
    else setViewMonth(v => v-1)
  }
  function nextMonth() {
    if (viewMonth === 11) { setViewYear(v => v+1); setViewMonth(0) }
    else setViewMonth(v => v+1)
  }

  const displayDate = selDay
    ? `${String(selDay).padStart(2,"0")} ${MONTHS_SHORT[selMonth]} ${selYear}`
    : "Select date"

  const totalDays = daysInMonth(viewYear, viewMonth)
  const startDay  = firstDayOfMonth(viewYear, viewMonth)
  const yearRange = Array.from({length: 11}, (_,i) => viewYear - 5 + i)

  const inputNum = "w-[40px] text-center text-sm text-ink bg-transparent focus:outline-none"

  return (
    <div ref={ref} className="relative mt-1">
      {/* Main row */}
      <div className="flex h-[46px] rounded-lg border border-[#E0DDD8] bg-surface overflow-hidden focus-within:border-brand-pink transition-colors">

        {/* Date trigger */}
        <div
          className="flex-1 flex items-center px-3 text-sm cursor-pointer select-none"
          onClick={() => { setOpen(o => !o); setYearMode(false) }}
        >
          <span className={selDay ? "text-ink" : "text-ink-muted"}>{displayDate}</span>
        </div>

        <div className="self-stretch w-px bg-[#E0DDD8] flex-shrink-0" />

        {/* Time: HH : MM AM/PM */}
        <div className="flex items-center gap-0.5 px-2" onClick={e => e.stopPropagation()}>
          <input
            type="text" inputMode="numeric" maxLength={2}
            value={hour}
            onChange={e => {
              const v = e.target.value.replace(/\D/g,"").slice(0,2)
              setHour(v)
              emitDate(selYear, selMonth, selDay, v, minute, period)
            }}
            placeholder="HH"
            className={inputNum}
          />
          <span className="text-ink-muted text-sm font-bold">:</span>
          <input
            type="text" inputMode="numeric" maxLength={2}
            value={minute}
            onChange={e => {
              const v = e.target.value.replace(/\D/g,"").slice(0,2)
              setMinute(v)
              emitDate(selYear, selMonth, selDay, hour, v, period)
            }}
            placeholder="MM"
            className={inputNum}
          />
          <button
            type="button"
            onClick={() => {
              const p = period === "AM" ? "PM" : "AM"
              setPeriod(p)
              emitDate(selYear, selMonth, selDay, hour, minute, p)
            }}
            className="ml-1 text-xs font-bold text-brand-pink bg-[#FCE2EE] rounded-md px-1.5 py-0.5 hover:bg-brand-pink hover:text-white transition-colors"
          >
            {period}
          </button>
        </div>
      </div>

      {/* Calendar popup */}
      {open && (
        <div className="absolute z-50 mt-1 left-0 w-[280px] bg-white rounded-xl border border-[#E0DDD8] shadow-lg p-3">
          {yearMode ? (
            <>
              <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2 text-center">Select Year</p>
              <div className="grid grid-cols-3 gap-1">
                {yearRange.map(y => (
                  <button key={y} type="button" onClick={() => pickYear(y)}
                    className={`rounded-lg py-2 text-sm font-semibold transition-colors
                      ${y === viewYear ? "bg-brand-pink text-white" : "hover:bg-[#F6F5F0] text-ink"}`}>
                    {y}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="flex items-center justify-between mb-2">
                <button type="button" onClick={prevMonth}
                  className="w-7 h-7 rounded-full hover:bg-[#F6F5F0] flex items-center justify-center text-ink-muted text-lg">‹</button>
                <button type="button" onClick={() => setYearMode(true)}
                  className="text-sm font-bold text-ink hover:text-brand-pink transition-colors">
                  {MONTHS_SHORT[viewMonth]} {viewYear}
                </button>
                <button type="button" onClick={nextMonth}
                  className="w-7 h-7 rounded-full hover:bg-[#F6F5F0] flex items-center justify-center text-ink-muted text-lg">›</button>
              </div>

              <div className="grid grid-cols-7 mb-1">
                {DAYS_OF_WEEK.map(d => (
                  <div key={d} className="text-center text-[10px] font-semibold text-ink-muted py-1">{d}</div>
                ))}
              </div>

              <div className="grid grid-cols-7 gap-y-0.5">
                {Array.from({length: startDay}).map((_,i) => <div key={`e${i}`} />)}
                {Array.from({length: totalDays}, (_,i) => i+1).map(d => {
                  const isSelected = d === selDay && viewMonth === selMonth && viewYear === selYear
                  const isToday    = d === today.getDate() && viewMonth === today.getMonth() && viewYear === today.getFullYear()
                  return (
                    <button key={d} type="button" onClick={() => pickDay(d)}
                      className={`h-8 w-full rounded-lg text-sm font-medium transition-colors
                        ${isSelected ? "bg-brand-pink text-white"
                          : isToday  ? "bg-[#FCE2EE] text-brand-pink font-bold"
                          : "hover:bg-[#F6F5F0] text-ink"}`}>
                      {d}
                    </button>
                  )
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
