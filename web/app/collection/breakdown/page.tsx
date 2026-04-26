import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth";
import { getCollectionSummary } from "@/lib/api";
import { rupee } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { ProgressBar } from "@/components/ui/progress-bar";
import Link from "next/link";

function _periodMonth(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function _monthLabel(d: Date): string {
  return d.toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

export default async function CollectionBreakdownPage() {
  const session = await getSession();
  if (!session) redirect("/login");

  const now = new Date();
  const period = _periodMonth(now);
  const monthLabel = _monthLabel(now);

  let data;
  try {
    data = await getCollectionSummary(period);
  } catch {
    return (
      <main className="px-4 pt-6 pb-24 max-w-lg mx-auto">
        <BackButton />
        <p className="text-sm text-ink-muted text-center mt-12">Unable to load collection data</p>
      </main>
    );
  }

  return (
    <main className="flex flex-col gap-4 px-4 pt-6 pb-24 max-w-lg mx-auto">
      <div className="flex items-center gap-3">
        <BackButton />
        <div>
          <p className="text-xs text-ink-muted font-medium">{monthLabel}</p>
          <h1 className="text-lg font-extrabold text-ink leading-tight">Collection Breakdown</h1>
        </div>
      </div>

      {/* Summary bar */}
      <Card className="p-5">
        <div className="flex items-baseline gap-1.5">
          <span className="text-3xl font-extrabold text-ink leading-none">
            {rupee(data.collected)}
          </span>
          <span className="text-sm text-ink-muted font-medium">of {rupee(data.expected)}</span>
        </div>
        <div className="mt-3">
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

      {/* Section 1: Counted in Total Collection */}
      <Section
        title="Counted in Total Collection"
        accent="text-status-paid"
        items={[
          { label: "Rent collected", value: data.rent_collected },
          { label: "Maintenance collected", value: data.maintenance_collected },
        ]}
        total={data.collected}
        totalLabel="Total collected"
      />

      {/* Section 2: Pending */}
      {data.pending > 0 && (
        <Section
          title="Pending (not yet collected)"
          accent="text-status-due"
          items={[{ label: "Outstanding rent + maintenance", value: data.pending }]}
          total={data.pending}
          totalLabel="Total pending"
          totalColor="text-status-due"
        />
      )}

      {/* Section 3: Separate (not in Total Collection) */}
      {(data.deposits_received > 0 || data.booking_advances > 0) && (
        <Section
          title="Tracked separately (NOT in Total Collection)"
          accent="text-brand-blue"
          items={[
            ...(data.deposits_received > 0
              ? [{ label: "Security deposits received", value: data.deposits_received }]
              : []),
            ...(data.booking_advances > 0
              ? [{ label: "Booking advances received", value: data.booking_advances }]
              : []),
          ]}
          total={data.deposits_received + data.booking_advances}
          totalLabel="Total tracked separately"
          totalColor="text-brand-blue"
          note="Per Kozzy reporting rules — deposits & advances are recorded but excluded from the monthly collection figure."
        />
      )}
    </main>
  );
}

function BackButton() {
  return (
    <Link
      href="/"
      className="w-9 h-9 rounded-full bg-[#F0EDE9] flex items-center justify-center text-ink-muted flex-shrink-0"
      aria-label="Back to home"
    >
      ←
    </Link>
  );
}

function Section({
  title,
  accent,
  items,
  total,
  totalLabel,
  totalColor = "text-ink",
  note,
}: {
  title: string;
  accent: string;
  items: { label: string; value: number }[];
  total: number;
  totalLabel: string;
  totalColor?: string;
  note?: string;
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
