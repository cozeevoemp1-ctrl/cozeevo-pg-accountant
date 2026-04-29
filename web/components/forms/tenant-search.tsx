"use client"

import { useState, useRef } from "react"
import { searchTenants, TenantSearchResult } from "@/lib/api"

interface TenantSearchProps {
  onSelect: (tenant: TenantSearchResult) => void
  defaultValue?: string
  defaultTenant?: TenantSearchResult
  placeholder?: string
}

export function TenantSearch({ onSelect, defaultValue = "", defaultTenant, placeholder = "Search by name or room..." }: TenantSearchProps) {
  const [query, setQuery] = useState(defaultTenant ? `${defaultTenant.name} — Room ${defaultTenant.room_number}` : defaultValue)
  const [results, setResults] = useState<TenantSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<TenantSearchResult | null>(defaultTenant ?? null)
  const [open, setOpen] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  async function runSearch(q: string) {
    if (q.trim().length < 1) { setResults([]); setOpen(false); return }
    setLoading(true)
    try {
      const data = await searchTenants(q.trim())
      setResults(data)
      setOpen(data.length > 0)
    } catch {
      setResults([])
      setOpen(false)
    } finally {
      setLoading(false)
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value
    setQuery(val)
    setSelected(null)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => runSearch(val), 300)
  }

  function handleSelect(t: TenantSearchResult) {
    setSelected(t)
    setQuery(`${t.name} — Room ${t.room_number}`)
    setOpen(false)
    onSelect(t)
  }

  function handleClear() {
    setSelected(null)
    setQuery("")
    setResults([])
    setOpen(false)
  }

  return (
    <div className="relative">
      <label className="block text-xs font-semibold text-ink-muted mb-1">Tenant</label>
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={handleInput}
          onFocus={() => results.length > 0 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={placeholder}
          className="w-full rounded-pill border border-[#E2DEDD] bg-surface px-4 py-3 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
        />
        {loading && (
          <span className="absolute right-4 top-1/2 -translate-y-1/2 text-ink-muted text-xs">...</span>
        )}
      </div>
      {open && results.length > 0 && (
        <ul className="absolute z-20 mt-1 w-full bg-surface rounded-tile shadow-lg border border-[#E2DEDD] max-h-56 overflow-y-auto">
          {results.map((t) => (
            <li
              key={t.tenancy_id}
              onMouseDown={() => handleSelect(t)}
              className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-bg active:bg-tile-pink"
            >
              <div>
                <p className="font-semibold text-ink text-sm">{t.name}</p>
                <p className="text-ink-muted text-xs">Room {t.room_number} · {t.building_code}</p>
              </div>
              <span className="text-xs text-ink-muted">₹{t.rent.toLocaleString("en-IN")}/mo</span>
            </li>
          ))}
        </ul>
      )}
      {selected && (
        <div className="mt-2 rounded-tile bg-tile-pink px-3 py-2 text-xs text-ink flex justify-between items-center">
          <span className="font-medium">{selected.name} · Room {selected.room_number} · {selected.building_code}</span>
          <button onClick={handleClear} className="text-ink-muted ml-2 font-bold">✕</button>
        </div>
      )}
    </div>
  )
}
