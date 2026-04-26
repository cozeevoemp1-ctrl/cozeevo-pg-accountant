"use client"

interface ConfirmField {
  label: string
  value: string
  highlight?: boolean
}

interface ConfirmationCardProps {
  title: string
  fields: ConfirmField[]
  onConfirm: () => void
  onEdit: () => void
  loading?: boolean
}

export function ConfirmationCard({ title, fields, onConfirm, onEdit, loading = false }: ConfirmationCardProps) {
  return (
    <div className="fixed inset-0 z-30 flex items-end justify-center bg-black/40">
      <div className="w-full max-w-md bg-surface rounded-t-[28px] px-6 pt-5 pb-10 shadow-2xl">
        <div className="w-10 h-1 bg-[#E2DEDD] rounded-full mx-auto mb-5" />
        <h2 className="text-lg font-extrabold text-ink mb-4">{title}</h2>

        <div className="divide-y divide-[#F0EDE9] mb-6">
          {fields.map((f) => (
            <div key={f.label} className="flex justify-between py-3">
              <span className="text-sm text-ink-muted">{f.label}</span>
              <span className={`text-sm font-semibold ${f.highlight ? "text-brand-pink text-base font-extrabold" : "text-ink"}`}>
                {f.value}
              </span>
            </div>
          ))}
        </div>

        <button
          onClick={onConfirm}
          disabled={loading}
          className="w-full rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80 disabled:opacity-50 mb-3"
        >
          {loading ? "Saving…" : "Confirm & Save ✓"}
        </button>
        <button
          onClick={onEdit}
          disabled={loading}
          className="w-full rounded-pill border border-[#E2DEDD] py-3 text-ink font-semibold text-sm active:opacity-80 disabled:opacity-50"
        >
          Edit
        </button>
      </div>
    </div>
  )
}
