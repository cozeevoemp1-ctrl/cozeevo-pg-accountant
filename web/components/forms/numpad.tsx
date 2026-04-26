"use client"

interface NumpadProps {
  value: string
  onChange: (value: string) => void
  suggestAmounts?: number[]
}

export function Numpad({ value, onChange, suggestAmounts = [] }: NumpadProps) {
  function press(key: string) {
    if (key === "⌫") {
      onChange(value.slice(0, -1))
      return
    }
    if (value === "0") return
    if (value.length >= 7) return
    onChange(value + key)
  }

  const display = value ? Number(value).toLocaleString("en-IN") : "0"

  return (
    <div className="bg-[#0F0E0D] rounded-tile p-4">
      <div className="text-center mb-3">
        <p className="text-xs font-semibold text-[#666] uppercase tracking-wide mb-1">Amount</p>
        <p className="text-4xl font-extrabold text-white tracking-tight">
          <span className="text-2xl text-[#888] mr-1">₹</span>{display}
        </p>
      </div>

      {suggestAmounts.length > 0 && (
        <div className="flex gap-2 justify-center mb-3">
          {suggestAmounts.map((amt) => (
            <button
              key={amt}
              type="button"
              onClick={() => onChange(String(amt))}
              className={`px-3 py-1.5 rounded-full text-xs font-bold border transition-colors ${
                value === String(amt)
                  ? "border-brand-pink text-brand-pink bg-brand-pink/10"
                  : "border-[#333] text-[#888]"
              }`}
            >
              ₹{amt.toLocaleString("en-IN")}
            </button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-3 gap-2">
        {["1","2","3","4","5","6","7","8","9"].map((k) => (
          <button key={k} type="button" onClick={() => press(k)}
            className="bg-[#1a1a1a] rounded-[10px] py-3 text-white font-bold text-lg text-center active:scale-95 transition-transform">
            {k}
          </button>
        ))}
        <button type="button" onClick={() => press("0")}
          className="col-span-2 bg-[#1a1a1a] rounded-[10px] py-3 text-white font-bold text-lg text-center active:scale-95 transition-transform">
          0
        </button>
        <button type="button" onClick={() => press("⌫")}
          className="bg-[#1a1a1a] rounded-[10px] py-3 text-[#888] text-sm font-bold text-center active:scale-95 transition-transform">
          ⌫
        </button>
      </div>
    </div>
  )
}
