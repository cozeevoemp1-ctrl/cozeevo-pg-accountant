import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth-server";
import { getCollectionHistory } from "@/lib/api";
import { rupee } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { ProgressBar } from "@/components/ui/progress-bar";
import Link from "next/link";

function _monthLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

export default async function CollectionHistoryPage() {
  const session = await getSession();
  if (!session) redirect("/login");

  const token = session.session.access_token;
  let months;
  try {
    months = await getCollectionHistory(6, token);
  } catch {
    return (
      <main className="px-4 pt-6 pb-24 max-w-lg mx-auto">
        <BackButton />
        <p className="text-sm text-ink-muted text-center mt-12">Unable to load collection history</p>
      </main>
    );
  }

  // Total collected across all months shown
  const grandTotal = months.reduce((s, m) => s + m.collected, 0);

  return (
    <main className="flex flex-col gap-4 px-4 pt-6 pb-24 max-w-lg mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <BackButton />
        <div>
          <p className="text-xs text-ink-muted font-medium">Last 6 months</p>
          <h1 className="text-lg font-extrabold text-ink leading-tight">Collection History</h1>
        </div>
      </div>

      {/* Grand total banner */}
      <Card className="p-4 bg-ink text-bg">
        <p className="text-xs font-semibold opacity-60 uppercase tracking-wide">6-month total collected</p>
        <p className="text-3xl font-extrabold mt-0.5 leading-none">{rupee(grandTotal)}</p>
      </Card>

      {/* Month-by-month cards */}
      {months.map((data) => {
        const cashAmt = data.method_breakdown?.cash ?? 0;
        const upiAmt = data.method_breakdown?.upi ?? 0;
        const otherAmt = Object.entries(data.method_breakdown ?? {})
          .filter(([k]) => k !== "cash" && k !== "upi")
          .reduce((s, [, v]) => s + v, 0);

        return (
          <Card key={data.period_month} className="p-4">
            {/* Month + % badge */}
            <div className="flex items-start justify-between mb-2">
              <div>
                <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">
                  {_monthLabel(data.period_month)}
                </p>
                <div className="flex items-baseline gap-1.5 mt-0.5">
                  <span className="text-2xl font-extrabold text-ink leading-none">
                    {rupee(data.collected)}
                  </span>
                  <span className="text-xs text-ink-muted font-medium">of {rupee(data.expected)}</span>
                </div>
              </div>
              <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${
                data.collection_pct >= 90
                  ? "bg-tile-green text-status-paid"
                  : data.collection_pct >= 70
                  ? "bg-amber-50 text-amber-700"
                  : "bg-red-50 text-red-600"
              }`}>
                {data.collection_pct}%
              </span>
            </div>

            {/* Progress bar */}
            <ProgressBar value={data.collection_pct} />

            {/* Method breakdown */}
            <div className="flex gap-2 mt-3 flex-wrap">
              {cashAmt > 0 && (
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-green-50 text-green-700 border border-green-200">
                  Cash {rupee(cashAmt)}
                </span>
              )}
              {upiAmt > 0 && (
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                  UPI {rupee(upiAmt)}
                </span>
              )}
              {otherAmt > 0 && (
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 border border-gray-200">
                  Other {rupee(otherAmt)}
                </span>
              )}
              {data.pending > 0 && (
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-red-50 text-status-due border border-red-200">
                  Pending {rupee(data.pending)}
                </span>
              )}
            </div>

            {/* Overdue count */}
            {data.overdue_count > 0 && (
              <p className="text-[11px] text-status-warn font-medium mt-2">
                {data.overdue_count} tenant{data.overdue_count !== 1 ? "s" : ""} not fully paid
              </p>
            )}

            {/* Drill-down link */}
            <Link
              href={`/collection/breakdown?month=${data.period_month}`}
              className="mt-3 block text-[11px] font-semibold text-brand-pink"
            >
              View breakdown →
            </Link>
          </Card>
        );
      })}
    </main>
  );
}

function BackButton() {
  return (
    <Link
      href="/collection/breakdown"
      className="w-9 h-9 rounded-full bg-[#F0EDE9] flex items-center justify-center text-ink-muted flex-shrink-0"
      aria-label="Back"
    >
      ←
    </Link>
  );
}
