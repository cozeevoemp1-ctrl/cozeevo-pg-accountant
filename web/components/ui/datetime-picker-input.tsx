"use client"

/**
 * DateTimePickerInput
 * Tap → bottom sheet: calendar grid + hour pills (scrollable) + minute buttons.
 * value / onChange: "YYYY-MM-DDTHH:MM"
 */

import { useState, useRef } from "react"

const DAY_LABELS  = ["Mo","Tu","We","Th","Fr","Sa","Su"]
const MONTH_NAMES = ["January","February","March","April","May","June",
                     "July","August","September","October","November","December"]
const MONTH_SHORT = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
const HOURS   = Array.from({ length: 24 }, (_, i) => i)
const MINUTES = [0, 15, 30, 45]

function fmtHour(h: number) {
  if (h === 0)  return "12 am"
  if (h < 12)   return `${h} am`
  if (h === 12) return "12 pm"
  return `${h - 12} pm`
}

interface Props {
  value:    string   // "YYYY-MM-DDTHH:MM" or ""
  onChange: (v: string) => void
  placeholder?: string
}

export function DateTimePickerInput({ value, onChange, placeholder = "Select date & time" }: Props) {
  const today  = new Date()
  const [datePart, timePart] = value ? value.split("T") : ["",""]
  const parsed = datePart ? new Date(datePart + "T00:00:00") : null
  const hour   = timePart ? parseInt(timePart.split(":")[0]) : -1
  const minute = timePart ? parseInt(timePart.split(":")[1]) : -1

  const [open, setOpen]           = useState(false)
  const [viewYear, setViewYear]   = useState(parsed?.getFullYear()  ?? today.getFullYear())
  const [viewMonth, setViewMonth] = useState(parsed?.getMonth()     ?? today.getMonth())
  const [pickedDate, setPickedDate] = useState(datePart)
  const [pickedHour, setPickedHour] = useState(hour)
  const [pickedMin,  setPickedMin]  = useState(minute)
  const hourRowRef = useRef<HTMLDivElement>(null)

  const offset    = (new Date(viewYear, viewMonth, 1).getDay() + 6) % 7
  const totalDays = new Date(viewYear, viewMonth + 1, 0).getDate()
  const selParsed = pickedDate ? new Date(pickedDate + "T00:00:00") : null
  const selDay    = selParsed && selParsed.getFullYear() === viewYear && selParsed.getMonth() === viewMonth
    ? selParsed.getDate() : null

  function prevMonth() {
    if (viewMonth === 0) { setViewYear(y => y - 1); setViewMonth(11) }
    else setViewMonth(m => m - 1)
  }
  function nextMonth() {
    if (viewMonth === 11) { setViewYear(y => y + 1); setViewMonth(0) }
    else setViewMonth(m => m + 1)
  }

  function pickDay(day: number) {
    const d = `${viewYear}-${String(viewMonth+1).padStart(2,"0")}-${String(day).padStart(2,"0")}`
    setPickedDate(d)
  }

  function confirm() {
    if (!pickedDate) return
    const h = pickedHour >= 0 ? pickedHour : 9
    const m = pickedMin  >= 0 ? pickedMin  : 0
    onChange(`${pickedDate}T${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}`)
    setOpen(false)
  }

  function openSheet() {
    // Reset internal state to current value
    setPickedDate(datePart)
    setPickedHour(hour)
    setPickedMin(minute)
    if (parsed) { setViewYear(parsed.getFullYear()); setViewMonth(parsed.getMonth()) }
    setOpen(true)
  }

  // Display string
  const displayDate = parsed
    ? `${String(parsed.getDate()).padStart(2,"0")} ${MONTH_SHORT[parsed.getMonth()]} ${parsed.getFullYear()}`
    : ""
  const displayTime = hour >= 0 && minute >= 0
    ? `${fmtHour(hour).replace(" ","")} : ${String(minute).padStart(2,"0")}`
    : ""
  const display = displayDate ? `${displayDate}  ${displayTime}` : ""

  const canConfirm = !!pickedDate

  return (
    <>
      <button
        type="button"
        onClick={openSheet}
        className="mt-1 w-full h-[42px] rounded-lg border border-[#E0DDD8] bg-surface px-3 text-sm text-left flex items-center active:border-brand-pink"
      >
        <span className={display ? "text-ink" : "text-ink-muted"}>{display || placeholder}</span>
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex flex-col justify-end">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div className="relative bg-surface rounded-t-2xl px-4 pt-4 pb-8 max-h-[90vh] overflow-y-auto">
            <div className="w-10 h-1 bg-[#D9D9D9] rounded-full mx-auto mb-4" />

            {/* Month nav */}
            <div className="flex items-center justify-between mb-3">
              <button type="button" onClick={prevMonth}
                className="w-9 h-9 rounded-full active:bg-[#F0EDE9] flex items-center justify-center text-xl text-ink-muted font-bold">‹</button>
              <span className="text-base font-extrabold text-ink">{MONTH_NAMES[viewMonth]} {viewYear}</span>
              <button type="button" onClick={nextMonth}
                className="w-9 h-9 rounded-full active:bg-[#F0EDE9] flex items-center justify-center text-xl text-ink-muted font-bold">›</button>
            </div>

            {/* Day headers */}
            <div className="grid grid-cols-7 mb-1">
              {DAY_LABELS.map(d => (
                <div key={d} className="text-center text-[11px] font-semibold text-ink-muted py-1">{d}</div>
              ))}
            </div>

            {/* Calendar grid */}
            <div className="grid grid-cols-7 gap-y-1 mb-5">
              {Array.from({ length: offset }, (_, i) => <div key={"e"+i} />)}
              {Array.from({ length: totalDays }, (_, i) => {
                const day = i + 1
                const isSel = day === selDay
                const isToday = viewYear === today.getFullYear() && viewMonth === today.getMonth() && day === today.getDate()
                return (
                  <button key={day} type="button" onClick={() => pickDay(day)}
                    className={`mx-auto w-9 h-9 flex items-center justify-center rounded-full text-sm font-medium transition-colors
                      ${isSel   ? "bg-brand-pink text-white font-bold"
                      : isToday ? "border-2 border-brand-pink text-brand-pink font-semibold"
                      : "text-ink active:bg-[#F0EDE9]"}`}>
                    {day}
                  </button>
                )
              })}
            </div>

            {/* Hour pills — horizontal scroll */}
            <p className="text-[11px] font-semibold text-ink-muted uppercase tracking-wide mb-2">Hour</p>
            <div ref={hourRowRef} className="flex gap-2 overflow-x-auto pb-2 no-scrollbar mb-4">
              {HOURS.map(h => (
                <button key={h} type="button" onClick={() => setPickedHour(h)}
                  className={`flex-shrink-0 px-3.5 py-2 rounded-pill text-xs font-semibold transition-colors
                    ${pickedHour === h ? "bg-brand-pink text-white" : "bg-[#F0EDE9] text-ink active:opacity-70"}`}>
                  {fmtHour(h)}
                </button>
              ))}
            </div>

            {/* Minute slots */}
            <p className="text-[11px] font-semibold text-ink-muted uppercase tracking-wide mb-2">Minute</p>
            <div className="grid grid-cols-4 gap-2 mb-5">
              {MINUTES.map(m => (
                <button key={m} type="button" onClick={() => setPickedMin(m)}
                  className={`py-2.5 rounded-xl text-sm font-bold transition-colors
                    ${pickedMin === m ? "bg-brand-pink text-white" : "bg-[#F0EDE9] text-ink active:opacity-70"}`}>
                  :{String(m).padStart(2,"0")}
                </button>
              ))}
            </div>

            {/* Confirm */}
            <button type="button" onClick={confirm} disabled={!canConfirm}
              className="w-full py-3 rounded-xl bg-brand-pink text-white text-sm font-bold disabled:opacity-40 active:opacity-80">
              {pickedDate
                ? `Confirm — ${String(new Date(pickedDate+"T00:00:00").getDate()).padStart(2,"0")} ${MONTH_SHORT[new Date(pickedDate+"T00:00:00").getMonth()]}${pickedHour >= 0 ? `, ${fmtHour(pickedHour)}` : ""}`
                : "Select a date first"}
            </button>
          </div>
        </div>
      )}
    </>
  )
}
