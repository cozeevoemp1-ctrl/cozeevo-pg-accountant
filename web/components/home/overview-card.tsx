import { Card } from "@/components/ui/card";
import { ProgressBar } from "@/components/ui/progress-bar";
import { rupee } from "@/lib/format";
import type { CollectionSummary } from "@/lib/api";

interface OverviewCardProps {
  data: CollectionSummary;
  month: string; // e.g. "April 2026"
}

export function OverviewCard({ data, month }: OverviewCardProps) {
  return (
    <Card className="p-5">
      <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">
        {month} · Collection
      </p>

      <div className="mt-3">
        <p className="text-xs text-ink-muted">Collected this month</p>
        <div className="flex items-baseline gap-1.5 mt-0.5">
          <span className="text-3xl font-extrabold text-ink leading-none">
            {rupee(data.collected)}
          </span>
          <span className="text-sm text-ink-muted font-medium">
            of {rupee(data.expected)}
          </span>
        </div>
      </div>

      <div className="mt-4">
        <ProgressBar value={data.collection_pct} />
        <div className="flex justify-between mt-1.5">
          <span className="text-xs text-ink-muted">{data.collection_pct}% collected</span>
          <span className="text-xs text-status-due font-semibold">
            {rupee(data.pending)} pending
          </span>
        </div>
      </div>

      {data.overdue_count > 0 && (
        <p className="mt-3 text-xs text-status-warn font-medium">
          {data.overdue_count} tenant{data.overdue_count !== 1 ? "s" : ""} overdue
        </p>
      )}
    </Card>
  );
}
