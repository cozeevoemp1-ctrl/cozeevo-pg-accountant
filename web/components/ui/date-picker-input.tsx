"use client"

/**
 * DatePickerInput
 * Shows as a tappable field. Tap → bottom sheet with calendar grid.
 * value / onChange: "YYYY-MM-DD"
 */

import { useState } from "react"

const DAY_LABELS  = ["Mo","Tu","We","Th","Fr","Sa","Su"]
const MONTH_NAMES = ["January","February","March","April","May","June",
                     "July","August","September","October","November","December"]
const MONTH_SHORT = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

interface Props {
  value:    string
  onChange: (v: string) => void
  placeholder?: string
}

export function DatePickerInput({ value, onChange, placeholder = "Select date" }: Props) {
  const today    = new Date()
  const parsed   = value ? new Date(value + "T00:00:00") : null

  const [open, setOpen]         = useState(false)
  const [viewYear, setViewYear] = useState(parsed?.getFullYear()  ?? today.getFullYear())
  const [viewMonth, setViewMonth] = useState(parsed?.getMonth() ?? today.getMonth())

  const offset   = (new Date(viewYear, viewMonth, 1).getDay() + 6) % 7
  const totalDays = new Date(viewYear, viewMonth + 1, 0).getDate()
  const selDay   = parsed && parsed.getFullYear() === viewYear && parsed.getMonth() === viewMonth
    ? parsed.getDate() : null

  function prevMonth() {
    if (viewMonth === 0) { setViewYear(y => y - 1); setViewMonth(11) }
    else setViewMonth(m => m - 1)
  }
  function nextMonth() {
    if (viewMonth === 11) { setViewYear(y => y + 1); setViewMonth(0) }
    else setViewMonth(m => m + 1)
  }
  function pick(day: number) {
    onChange(`${viewYear}-${String(viewMonth+1).padStart(2,"0")}-${String(day).padStart(2,"0")}`)
    setOpen(false)
  }

  const display = parsed
    ? `${String(parsed.getDate()).padStart(2,"0")} ${MONTH_SHORT[parsed.getMonth()]} ${parsed.getFullYear()}`
    : ""

  return (
    <>
      {/* Field trigger */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-1 w-full h-[42px] rounded-lg border border-[#E0DDD8] bg-surface px-3 text-sm text-left flex items-center active:border-brand-pink"
      >
        <span className={display ? "text-ink" : "text-ink-muted"}>{display || placeholder}</span>
      </button>

      {/* Bottom sheet overlay */}
      {open && (
        <div className="fixed inset-0 z-50 flex flex-col justify-end">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div className="relative bg-surface rounded-t-2xl px-4 pt-4 pb-8">
            {/* Handle */}
            <div className="w-10 h-1 bg-[#D9D9D9] rounded-full mx-auto mb-4" />

            {/* Month nav */}
            <div className="flex items-center justify-between mb-3">
              <button type="button" onClick={prevMonth}
                className="w-9 h-9 rounded-full active:bg-[#F0EDE9] flex items-center justify-center text-xl text-ink-muted font-bold">
                ‹
              </button>
              <span className="text-base font-extrabold text-ink">
                {MONTH_NAMES[viewMonth]} {viewYear}
              </span>
              <button type="button" onClick={nextMonth}
                className="w-9 h-9 rounded-full active:bg-[#F0EDE9] flex items-center justify-center text-xl text-ink-muted font-bold">
                ›
              </button>
            </div>

            {/* Day-of-week headers */}
            <div className="grid grid-cols-7 mb-1">
              {DAY_LABELS.map(d => (
                <div key={d} className="text-center text-[11px] font-semibold text-ink-muted py-1">{d}</div>
              ))}
            </div>

            {/* Calendar grid */}
            <div className="grid grid-cols-7 gap-y-1">
              {Array.from({ length: offset }, (_, i) => <div key={"e"+i} />)}
              {Array.from({ length: totalDays }, (_, i) => {
                const day = i + 1
                const isSel = day === selDay
                const isToday = viewYear === today.getFullYear() && viewMonth === today.getMonth() && day === today.getDate()
                return (
                  <button key={day} type="button" onClick={() => pick(day)}
                    className={`mx-auto w-9 h-9 flex items-center justify-center rounded-full text-sm font-medium transition-colors
                      ${isSel    ? "bg-brand-pink text-white font-bold"
                      : isToday  ? "border-2 border-brand-pink text-brand-pink font-semibold"
                      : "text-ink active:bg-[#F0EDE9]"}`}>
                    {day}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
