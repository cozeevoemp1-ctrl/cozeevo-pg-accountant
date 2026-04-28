import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth-server";
import { getCollectionSummary, getDepositsHeld } from "@/lib/api";
import { rupee } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { ProgressBar } from "@/components/ui/progress-bar";
import Link from "next/link";

function _periodMonth(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function _monthLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

function _prevMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 2, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function _nextMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const METHOD_LABELS: Record<string, string> = {
  cash: "Cash",
  upi: "UPI",
  bank_transfer: "Bank transfer",
  cheque: "Cheque",
};

export default async function CollectionBreakdownPage({
  searchParams,
}: {
  searchParams: Promise<{ month?: string }>;
}) {
  const session = await getSession();
  if (!session) redirect("/login");

  const params = await searchParams;
  const now = new Date();
  const currentPeriod = _periodMonth(now);
  const period = params.month ?? currentPeriod;
  const isCurrentMonth = period === currentPeriod;
  const nextPeriod = _nextMonth(period);
  const prevPeriod = _prevMonth(period);

  const token = session.session.access_token;
  let data;
  let depositsData = { held: 0, maintenance: 0, refundable: 0 };
  try {
    const [col, dep] = await Promise.all([
      getCollectionSummary(period, token),
      getDepositsHeld(token),
    ]);
    data = col;
    depositsData = dep;
  } catch {
    return (
      <main className="px-4 pt-6 pb-24 max-w-lg mx-auto">
        <BackButton />
        <p className="text-sm text-ink-muted text-center mt-12">Unable to load collection data</p>
      </main>
    );
  }

  const methods = Object.entries(data.method_breakdown ?? {})
    .filter(([, v]) => v > 0)
    .sort(([, a], [, b]) => b - a);

  return (
    <main className="flex flex-col gap-4 px-4 pt-6 pb-24 max-w-lg mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <BackButton />
        <div>
          <p className="text-xs text-ink-muted font-medium">Collection breakdown</p>
          <h1 className="text-lg font-extrabold text-ink leading-tight">Money Dashboard</h1>
        </div>
      </div>

      {/* Month navigation */}
      <div className="flex items-center justify-between bg-surface rounded-tile px-4 py-2.5 border border-[#E0DDD8]">
        <Link href={`/collection/breakdown?month=${prevPeriod}`} className="text-brand-pink font-bold text-xl px-1 leading-none">‹</Link>
        <span className="text-sm font-semibold text-ink">{_monthLabel(period)}</span>
        <Link
          href={isCurrentMonth ? "#" : `/collection/breakdown?month=${nextPeriod}`}
          className={`font-bold text-xl px-1 leading-none ${isCurrentMonth ? "text-ink-muted opacity-30 pointer-events-none" : "text-brand-pink"}`}
        >›</Link>
      </div>

      {/* Summary */}
      <Card className="p-5">
        <div className="flex items-baseline gap-1.5">
          <span className="text-3xl font-extrabold text-ink leading-none">{rupee(data.collected)}</span>
          <span className="text-sm text-ink-muted font-medium">of {rupee(data.expected)}</span>
        </div>
        <div className="mt-3">
          <ProgressBar value={data.collection_pct} />
          <div className="flex justify-between mt-1.5">
            <span className="text-xs text-ink-muted">{data.collection_pct}% collected</span>
            <span className="text-xs text-status-due font-semibold">{rupee(data.pending)} pending</span>
          </div>
        </div>
        {data.overdue_count > 0 && (
          <p className="mt-3 text-xs text-status-warn font-medium">
            {data.overdue_count} tenant{data.overdue_count !== 1 ? "s" : ""} overdue
          </p>
        )}
      </Card>

      {/* Pure rent */}
      <Section
        title="Rent collected this month"
        accent="text-status-paid"
        items={[
          { label: "Pure rent", value: data.rent_collected },
          { label: "Maintenance", value: data.maintenance_collected },
        ]}
        total={data.collected}
        totalLabel="Total collected"
        totalColor="text-status-paid"
        note="Deposits and booking advances excluded."
      />

      {/* How it was paid */}
      {methods.length > 0 && (
        <Section
          title="How it was paid"
          accent="text-brand-blue"
          items={methods.map(([k, v]) => ({ label: METHOD_LABELS[k] ?? k, value: v }))}
          total={data.collected}
          totalLabel="Total"
          totalColor="text-brand-blue"
        />
      )}

      {/* Pending */}
      {data.pending > 0 && (
        <Section
          title="Pending"
          accent="text-status-due"
          items={[{ label: "Outstanding rent + maintenance", value: data.pending }]}
          total={data.pending}
          totalLabel="Total pending"
          totalColor="text-status-due"
        />
      )}

      {/* Deposits held — from active tenancy agreements */}
      <Section
        title="Security deposits held"
        accent="text-brand-pink"
        items={[
          { label: "Refundable", value: depositsData.refundable },
          { label: "Maintenance (non-refundable)", value: depositsData.maintenance },
        ]}
        total={depositsData.held}
        totalLabel="Total held"
        totalColor="text-brand-pink"
        note="From active tenancy agreements. Net refundable = held minus maintenance."
      />

      {/* Deposits this month */}
      {(data.deposits_received > 0 || data.booking_advances > 0) && (
        <Section
          title={`Received in ${_monthLabel(period)} (not in collection)`}
          accent="text-brand-blue"
          items={[
            ...(data.deposits_received > 0 ? [{ label: "Security deposits", value: data.deposits_received }] : []),
            ...(data.booking_advances > 0 ? [{ label: "Booking advances", value: data.booking_advances }] : []),
          ]}
          total={data.deposits_received + data.booking_advances}
          totalLabel="Total"
          totalColor="text-brand-blue"
          note="Tracked separately — not counted in rent collection."
        />
      )}
    </main>
  );
}

function BackButton() {
  return (
    <Link href="/" className="w-9 h-9 rounded-full bg-[#F0EDE9] flex items-center justify-center text-ink-muted flex-shrink-0" aria-label="Back">
      ←
    </Link>
  );
}

function Section({ title, accent, items, total, totalLabel, totalColor = "text-ink", note }: {
  title: string; accent: string;
  items: { label: string; value: number }[];
  total: number; totalLabel: string; totalColor?: string; note?: string;
}) {
  return (
    <Card className="p-4">
      <p className={`text-xs font-semibold uppercase tracking-wide mb-3 ${accent}`}>{title}</p>
      <div className="flex flex-col gap-0">
        {items.map((item) => (
          <div key={item.label} className="flex justify-between py-2 border-b border-[#F0EDE9]">
            <span className="text-sm text-ink-muted">{item.label}</span>
            <span className="text-sm font-semibold text-ink">{rupee(item.value)}</span>
          </div>
        ))}
        <div className="flex justify-between pt-2">
          <span className="text-sm font-semibold text-ink">{totalLabel}</span>
          <span className={`text-sm font-bold ${totalColor}`}>{rupee(total)}</span>
        </div>
      </div>
      {note && <p className="text-xs text-ink-muted mt-3 leading-relaxed">{note}</p>}
    </Card>
  );
}
