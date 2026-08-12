"use client"

/**
 * THE overlay primitives — use these for every modal/bottom-sheet.
 * Never hand-roll `fixed inset-0` overlays in pages. See docs/UI_SYSTEM.md.
 *
 * Encodes two hard-won rules (memory/rules_workflow.md §9):
 *  - inline `zIndex: 9999` (arbitrary Tailwind z- classes get purged; tab bar is z-50)
 *  - Sheet bottom padding clears the nav bar + iPhone home indicator
 */
import { ReactNode } from "react"

function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button
      onClick={onClose}
      aria-label="Close"
      className="w-8 h-8 rounded-full bg-bg flex items-center justify-center text-ink-muted text-lg leading-none shrink-0"
    >
      ×
    </button>
  )
}

interface OverlayProps {
  open: boolean
  onClose: () => void
  title?: string
  /** default true — tap outside to close */
  closeOnBackdrop?: boolean
  children: ReactNode
}

/** Centered dialog card. */
export function Modal({ open, onClose, title, closeOnBackdrop = true, children }: OverlayProps) {
  if (!open) return null
  return (
    <div className="fixed inset-0 flex items-center justify-center p-4" style={{ zIndex: 9999 }}>
      <div
        className="absolute inset-0 bg-black/50"
        onClick={closeOnBackdrop ? onClose : undefined}
      />
      <div className="relative bg-surface rounded-card w-full max-w-md max-h-[85vh] overflow-y-auto p-5">
        {(title || onClose) && (
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-ink">{title}</h2>
            <CloseButton onClose={onClose} />
          </div>
        )}
        {children}
      </div>
    </div>
  )
}

/** Bottom sheet — slides content to the bottom edge, safe-area aware. */
export function Sheet({ open, onClose, title, closeOnBackdrop = true, children }: OverlayProps) {
  if (!open) return null
  return (
    <div className="fixed inset-0 flex items-end" style={{ zIndex: 9999 }}>
      <div
        className="absolute inset-0 bg-black/50"
        onClick={closeOnBackdrop ? onClose : undefined}
      />
      <div
        className="relative bg-surface rounded-t-card w-full max-h-[85vh] overflow-y-auto p-5"
        style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 80px)" }}
      >
        {(title || onClose) && (
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-ink">{title}</h2>
            <CloseButton onClose={onClose} />
          </div>
        )}
        {children}
      </div>
    </div>
  )
}
