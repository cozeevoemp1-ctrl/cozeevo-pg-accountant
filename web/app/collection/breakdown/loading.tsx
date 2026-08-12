import { Skeleton } from "@/components/ui/skeleton";

export default function CollectionLoading() {
  return (
    <main className="flex flex-col gap-4 px-4 pt-6 pb-24 max-w-lg mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Skeleton className="w-9 h-9" />
        <Skeleton className="h-5 w-40" />
      </div>

      {/* Month picker */}
      <div className="flex items-center justify-between bg-surface rounded-card border border-border px-4 py-3">
        <Skeleton className="w-8 h-8" />
        <Skeleton className="h-4 w-32" />
        <Skeleton className="w-8 h-8" />
      </div>

      {/* Summary stats */}
      <div className="bg-surface rounded-card border border-border p-5 flex flex-col gap-3">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-9 w-36" />
        <Skeleton className="h-2.5 w-full" />
        <div className="flex gap-4 pt-1">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 w-24" />
        </div>
      </div>

      {/* Payment method breakdown */}
      <div className="bg-surface rounded-card border border-border p-4 flex flex-col gap-3">
        <Skeleton className="h-3 w-32 mb-1" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex justify-between items-center">
            <Skeleton className="h-3.5 w-20" />
            <Skeleton className="h-3.5 w-24" />
          </div>
        ))}
      </div>

      {/* Tenant list */}
      <div className="flex flex-col gap-2">
        <Skeleton className="h-3 w-28" />
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="bg-surface rounded-card border border-border p-4 flex justify-between items-center">
            <div className="flex flex-col gap-1.5">
              <Skeleton className="h-3.5 w-32" />
              <Skeleton className="h-2.5 w-20" />
            </div>
            <div className="h-6 w-16 bg-border rounded-pill animate-pulse" />
          </div>
        ))}
      </div>
    </main>
  );
}
