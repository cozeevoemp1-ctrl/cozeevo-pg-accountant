import { Skeleton } from "@/components/ui/skeleton";

export default function HomeLoading() {
  return (
    <main className="flex flex-col gap-5 px-4 pt-6 pb-32 max-w-lg mx-auto">
      {/* Greeting */}
      <div className="flex flex-col gap-1.5">
        <Skeleton className="h-6 w-44" />
        <Skeleton className="h-3.5 w-28" />
      </div>

      {/* Overview card */}
      <div className="bg-surface rounded-card border border-border p-5 flex flex-col gap-3">
        <Skeleton className="h-3.5 w-32" />
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-2 w-full" />
        <div className="flex gap-4">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-20" />
        </div>
      </div>

      {/* KPI tiles 2×2 */}
      <div className="grid grid-cols-2 gap-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="bg-surface rounded-card border border-border p-4 flex flex-col gap-2">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-7 w-12" />
          </div>
        ))}
      </div>

      {/* Quick links row */}
      <div className="flex gap-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex-1 bg-surface border border-border rounded-card px-3 py-2.5 h-14 animate-pulse" />
        ))}
      </div>

      {/* Recent check-ins */}
      <div className="flex flex-col gap-2">
        <Skeleton className="h-3 w-28" />
        <div className="bg-surface rounded-card border border-border px-4 py-1">
          {[1, 2, 3].map((i) => (
            <div key={i} className="py-3 border-b border-border last:border-0 flex justify-between items-center">
              <div className="flex flex-col gap-1.5">
                <Skeleton className="h-3.5 w-32" />
                <Skeleton className="h-2.5 w-20" />
              </div>
              <div className="h-6 w-14 bg-border rounded-pill animate-pulse" />
            </div>
          ))}
        </div>
      </div>

      {/* Recent payments */}
      <div className="flex flex-col gap-2">
        <Skeleton className="h-3 w-28" />
        <div className="bg-surface rounded-card border border-border px-4 py-1">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="py-3 border-b border-border last:border-0 flex justify-between items-center">
              <div className="flex flex-col gap-1.5">
                <Skeleton className="h-3.5 w-36" />
                <Skeleton className="h-2.5 w-24" />
              </div>
              <Skeleton className="h-4 w-16" />
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
