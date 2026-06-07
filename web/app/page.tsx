import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth-server";
import { getCollectionSummary, getKpi, getKpiDetail, getRecentActivity, getRecentCheckins, type KpiDetailItem } from "@/lib/api";
import { Greeting } from "@/components/home/greeting";
import { OverviewCard } from "@/components/home/overview-card";
import { KpiGrid } from "@/components/home/kpi-grid";
import { ActivityFeed } from "@/components/home/activity-feed";
import { RecentCheckins } from "@/components/home/recent-checkins";
import { Card } from "@/components/ui/card";
import Link from "next/link";

// Always fetch fresh data — no caching
export const revalidate = 0;

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
  const [collection, kpi, activity, recentCheckins] = await Promise.allSettled([
    getCollectionSummary(period, token),
    getKpi(token),
    getRecentActivity(15, token),
    getRecentCheckins(10, token),
  ]);

  // Pre-fetch KPI detail data server-side so tiles open instantly (no client-side API call)
  const kpiValue = kpi.status === "fulfilled" ? kpi.value : null;
  let initialDetails: Record<string, KpiDetailItem[]> = {};
  if (kpiValue) {
    const types: string[] = ["occupied", "vacant", "dues"];
    if (kpiValue.checkins_today > 0 || kpiValue.checkouts_today > 0) types.push("checkins_today", "checkouts_today");
    if (kpiValue.no_show_count > 0) types.push("no_show");
    if (kpiValue.notices_count > 0) types.push("notices");
    const results = await Promise.allSettled(types.map((t) => getKpiDetail(t, undefined, token)));
    results.forEach((r, i) => {
      if (r.status === "fulfilled") initialDetails[types[i]] = r.value.items;
    });
  }

  return (
    <main className="flex flex-col gap-5 px-4 pt-6 pb-32 max-w-lg mx-auto">
      <Greeting session={session} />

      {collection.status === "fulfilled" && session.role === "admin" && (
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

      {/* ── Tenants ───────────────────────────────────────────────── */}
      <section>
        <h2 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Tenants</h2>
        <div className="grid grid-cols-3 gap-2">
          <Link href="/checkouts" className="bg-surface border border-[#F0EDE9] rounded-card px-3 py-3 flex flex-col gap-1 active:opacity-70">
            <span className="text-lg">🚪</span>
            <p className="text-xs font-bold text-ink leading-tight">Checkouts</p>
            <p className="text-[10px] text-ink-muted">This month</p>
          </Link>
          <Link href="/notices" className="bg-surface border border-[#F0EDE9] rounded-card px-3 py-3 flex flex-col gap-1 active:opacity-70">
            <span className="text-lg">📋</span>
            <p className="text-xs font-bold text-ink leading-tight">Notices</p>
            <p className="text-[10px] text-ink-muted">On notice</p>
          </Link>
          <Link href="/onboarding/bookings" className="bg-surface border border-[#F0EDE9] rounded-card px-3 py-3 flex flex-col gap-1 active:opacity-70">
            <span className="text-lg">🏷️</span>
            <p className="text-xs font-bold text-ink leading-tight">Bookings</p>
            <p className="text-[10px] text-ink-muted">Check-ins</p>
          </Link>
        </div>
        <Link href="/tenants/pre-register" className="mt-2 flex items-center gap-3 bg-surface border border-[#F0EDE9] rounded-card px-4 py-3 active:opacity-70">
          <span className="text-base">➕</span>
          <div className="flex-1">
            <p className="text-xs font-bold text-ink">Pre-register tenant</p>
            <p className="text-[10px] text-ink-muted">Future joiner — no room yet</p>
          </div>
          <span className="text-ink-muted text-sm">›</span>
        </Link>
      </section>

      {/* ── Operations ────────────────────────────────────────────── */}
      <section>
        <h2 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Operations</h2>
        <div className="grid grid-cols-2 gap-2">
          <Link href="/activity" className="bg-surface border border-[#F0EDE9] rounded-card px-3 py-3 flex flex-col gap-1 active:opacity-70">
            <span className="text-lg">📝</span>
            <p className="text-xs font-bold text-ink leading-tight">Activity log</p>
            <p className="text-[10px] text-ink-muted">Payments · check-ins</p>
          </Link>
          <Link href="/operations" className="bg-surface border border-[#F0EDE9] rounded-card px-3 py-3 flex flex-col gap-1 active:opacity-70">
            <span className="text-lg">⚡</span>
            <p className="text-xs font-bold text-ink leading-tight">Operations log</p>
            <p className="text-[10px] text-ink-muted">Power · gas · water</p>
          </Link>
        </div>
      </section>

      {/* ── Finance (admin only) ───────────────────────────────────── */}
      {session.role === "admin" && (
        <section>
          <h2 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Finance</h2>
          <Link href="/finance" className="flex items-center gap-3 bg-surface border border-[#F0EDE9] rounded-card px-4 py-3 active:opacity-70">
            <span className="text-base">📊</span>
            <div className="flex-1">
              <p className="text-xs font-bold text-ink">Finance & P&L</p>
              <p className="text-[10px] text-ink-muted">Upload statements · Download Excel</p>
            </div>
            <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-tile-pink text-brand-pink uppercase">Owner</span>
          </Link>
        </section>
      )}

      <section>
        <h2 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">
          Recent check-ins
        </h2>
        <Card className="px-4 py-1">
          {recentCheckins.status === "fulfilled" ? (
            <RecentCheckins items={recentCheckins.value.items} />
          ) : (
            <p className="text-sm text-ink-muted py-4 text-center">Unable to load check-ins</p>
          )}
        </Card>
      </section>

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
