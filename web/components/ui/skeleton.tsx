/** THE skeleton bar. Compose with width/height classes: `<Skeleton className="h-4 w-32" />` */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`bg-border rounded-full animate-pulse ${className}`} />
}
