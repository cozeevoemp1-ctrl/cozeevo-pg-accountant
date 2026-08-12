/** THE empty-state line. `<EmptyState>No payments found</EmptyState>` */
import { ReactNode } from "react"

export function EmptyState({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <p className={`text-sm text-ink-muted text-center py-6 ${className}`}>{children}</p>
}
