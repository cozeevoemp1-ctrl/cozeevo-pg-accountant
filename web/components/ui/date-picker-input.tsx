"use client"

/**
 * DatePickerInput
 * - Tap to open calendar popup
 * - Tap month/year header → year grid for fast selection
 * value / onChange: "YYYY-MM-DD"
 *
 * Uses fixed positioning so it escapes overflow:hidden/auto parent containers (modals).
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

interface Props {
  value:    string
  onChange: (v: string) => void
}

export function DatePickerInput({ value, onChange }: Props) {
  const today = new Date()

  const [selYear,  setSelYear]  = useState(() => value ? +value.split("-")[0] : today.getFullYear())
  const [selMonth, setSelMonth] = useState(() => value ? +value.split("-")[1] - 1 : today.getMonth())
  const [selDay,   setSelDay]   = useState(() => value ? +value.split("-")[2] : 0)

  const [open,      setOpen]     = useState(false)
  const [yearMode,  setYearMode] = useState(false)
  const [viewYear,  setViewYear] = useState(selYear)
  const [viewMonth, setViewMonth] = useState(selMonth)
  const [popupStyle, setPopupStyle] = useState<React.CSSProperties>({})

  const triggerRef = useRef<HTMLDivElement>(null)
  const popupRef   = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (
        triggerRef.current && !triggerRef.current.contains(e.target as Node) &&
        popupRef.current   && !popupRef.current.contains(e.target as Node)
      ) setOpen(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  // Recalculate fixed position whenever open
  useEffect(() => {
    if (!open || !triggerRef.current) return
    const rect = triggerRef.current.getBoundingClientRect()
    const spaceBelow = window.innerHeight - rect.bottom
    const popupH = 320 // approximate calendar height
    if (spaceBelow >= popupH || spaceBelow >= 220) {
      setPopupStyle({ top: rect.bottom + 6, left: rect.left, width: Math.max(rect.width, 280) })
    } else {
      setPopupStyle({ bottom: window.innerHeight - rect.top + 6, left: rect.left, width: Math.max(rect.width, 280) })
    }
  }, [open])

  function pickDay(d: number) {
    setSelYear(viewYear); setSelMonth(viewMonth); setSelDay(d)
    const ds = `${viewYear}-${String(viewMonth + 1).padStart(2,"0")}-${String(d).padStart(2,"0")}`
    onChange(ds)
    setOpen(false)
  }

  function pickYear(y: number) { setViewYear(y); setYearMode(false) }

  function prevMonth() {
    if (viewMonth === 0) { setViewYear(v => v - 1); setViewMonth(11) }
    else setViewMonth(v => v - 1)
  }
  function nextMonth() {
    if (viewMonth === 11) { setViewYear(v => v + 1); setViewMonth(0) }
    else setViewMonth(v => v + 1)
  }

  const displayDate = selDay
    ? `${String(selDay).padStart(2,"0")} ${MONTHS_SHORT[selMonth]} ${selYear}`
    : "Select date"

  const totalDays = daysInMonth(viewYear, viewMonth)
  const startDay  = firstDayOfMonth(viewYear, viewMonth)
  const yearRange = Array.from({length: 11}, (_,i) => viewYear - 5 + i)

  return (
    <div className="relative mt-1">
      {/* Trigger */}
      <div
        ref={triggerRef}
        onClick={() => { setOpen(o => !o); setYearMode(false) }}
        className="flex h-[46px] rounded-lg border border-[#E0DDD8] bg-surface items-center px-3 cursor-pointer select-none transition-colors hover:border-brand-pink"
      >
        <span className={`text-sm ${selDay ? "text-ink" : "text-ink-muted"}`}>{displayDate}</span>
        <span className="ml-auto text-ink-muted text-base">📅</span>
      </div>

      {/* Calendar popup — fixed so it escapes overflow:hidden/auto modals */}
      {open && (
        <div
          ref={popupRef}
          className="fixed z-[9999] bg-white rounded-xl border border-[#E0DDD8] shadow-xl p-3"
          style={popupStyle}
        >
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
