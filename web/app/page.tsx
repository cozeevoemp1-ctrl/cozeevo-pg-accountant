import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth-server";
import { getCollectionSummary, getKpi, getKpiDetail, getRecentActivity, type KpiDetailItem } from "@/lib/api";
import { Greeting } from "@/components/home/greeting";
import { OverviewCard } from "@/components/home/overview-card";
import { KpiGrid } from "@/components/home/kpi-grid";
import { ActivityFeed } from "@/components/home/activity-feed";
import { Card } from "@/components/ui/card";
import Link from "next/link";

function _monthLabel(d: Date): string {
  return d.toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

function _periodMonth(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default async function HomePage() {
  const session = await getSession();
  if (!session) redirect("/login");

  const now = new Date();
  const period = _periodMonth(now);
  const monthLabel = _monthLabel(now);

  const token = session.session.access_token;
  const [collection, kpi, activity] = await Promise.allSettled([
    getCollectionSummary(period, token),
    getKpi(token),
    getRecentActivity(15, token),
  ]);

  // Pre-fetch KPI detail data server-side so tiles open instantly (no client-side API call)
  const kpiValue = kpi.status === "fulfilled" ? kpi.value : null;
  let initialDetails: Record<string, KpiDetailItem[]> = {};
  if (kpiValue) {
    const types: string[] = ["occupied", "vacant", "dues"];
    if (kpiValue.checkins_today > 0 || kpiValue.checkouts_today > 0) types.push("checkins_today", "checkouts_today");
    if (kpiValue.no_show_count > 0) types.push("no_show");
    if (kpiValue.notices_count > 0) types.push("notices");
    const results = await Promise.allSettled(types.map((t) => getKpiDetail(t, token)));
    results.forEach((r, i) => {
      if (r.status === "fulfilled") initialDetails[types[i]] = r.value.items;
    });
  }

  return (
    <main className="flex flex-col gap-5 px-4 pt-6 pb-32 max-w-lg mx-auto">
      <Greeting session={session} />

      {collection.status === "fulfilled" && (
        <Link href="/collection/breakdown" className="block">
          <OverviewCard data={collection.value} month={monthLabel} />
        </Link>
      )}

      {kpiValue && (
        <section>
          <h2 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">
            Today at a glance
          </h2>
          <KpiGrid data={kpiValue} initialDetails={initialDetails} />
        </section>
      )}

      {/* Quick links */}
      <div className="flex gap-2">
        <Link href="/checkouts" className="flex-1 bg-surface border border-[#F0EDE9] rounded-card px-3 py-2.5 flex items-center gap-2 active:opacity-70">
          <span className="text-base">🚪</span>
          <div>
            <p className="text-xs font-bold text-ink">Checkouts</p>
            <p className="text-[10px] text-ink-muted">This month</p>
          </div>
        </Link>
        <Link href="/notices" className="flex-1 bg-surface border border-[#F0EDE9] rounded-card px-3 py-2.5 flex items-center gap-2 active:opacity-70">
          <span className="text-base">📋</span>
          <div>
            <p className="text-xs font-bold text-ink">Notices</p>
            <p className="text-[10px] text-ink-muted">On notice</p>
          </div>
        </Link>
        <Link href="/onboarding/sessions" className="flex-1 bg-surface border border-[#F0EDE9] rounded-card px-3 py-2.5 flex items-center gap-2 active:opacity-70">
          <span className="text-base">📝</span>
          <div>
            <p className="text-xs font-bold text-ink">Sessions</p>
            <p className="text-[10px] text-ink-muted">Onboarding</p>
          </div>
        </Link>
      </div>

      <section>
        <h2 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">
          Recent payments
        </h2>
        <Card className="px-4 py-1">
          {activity.status === "fulfilled" ? (
            <ActivityFeed items={activity.value.items} />
          ) : (
            <p className="text-sm text-ink-muted py-4 text-center">Unable to load activity</p>
          )}
        </Card>
      </section>
    </main>
  );
}
