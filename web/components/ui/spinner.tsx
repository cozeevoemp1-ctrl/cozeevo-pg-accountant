/** THE loading spinner. `<Spinner />` centered inside any container. */
export function Spinner({ className = "" }: { className?: string }) {
  return (
    <div
      className={`w-10 h-10 rounded-full border-4 border-brand-pink border-t-transparent animate-spin ${className}`}
      role="status"
      aria-label="Loading"
    />
  )
}
