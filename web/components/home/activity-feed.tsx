import { rupee } from "@/lib/format";
import type { ActivityItem } from "@/lib/api";

interface ActivityFeedProps {
  items: ActivityItem[];
}

function _shortDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

const METHOD_LABEL: Record<string, string> = {
  upi: "UPI",
  cash: "Cash",
  bank: "Bank",
  card: "Card",
};

export function ActivityFeed({ items }: ActivityFeedProps) {
  if (items.length === 0) {
    return (
      <p className="text-center text-sm text-ink-muted py-6">No recent payments</p>
    );
  }

  return (
    <div className="flex flex-col divide-y divide-[#F0EDE9]">
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-3 py-3">
          <div className="w-9 h-9 rounded-full bg-tile-blue flex items-center justify-center text-sm font-bold text-[#0077B6] flex-shrink-0">
            {(item.tenant_name[0] ?? "?").toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-ink truncate">{item.tenant_name}</p>
            <p className="text-xs text-ink-muted">
              Room {item.room_number} · {METHOD_LABEL[item.method] ?? item.method}
            </p>
          </div>
          <div className="text-right flex-shrink-0">
            <p className="text-sm font-bold text-status-paid">{rupee(item.amount)}</p>
            <p className="text-xs text-ink-muted">{_shortDate(item.payment_date)}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
