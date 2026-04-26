import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth";
import { getCollectionSummary, getKpi, getRecentActivity } from "@/lib/api";
import { Greeting } from "@/components/home/greeting";
import { OverviewCard } from "@/components/home/overview-card";
import { KpiGrid } from "@/components/home/kpi-grid";
import { ActivityFeed } from "@/components/home/activity-feed";
import { Card } from "@/components/ui/card";

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

  const [collection, kpi, activity] = await Promise.allSettled([
    getCollectionSummary(period),
    getKpi(),
    getRecentActivity(15),
  ]);

  return (
    <main className="flex flex-col gap-5 px-4 pt-6 pb-24 max-w-lg mx-auto">
      <Greeting session={session} />

      {collection.status === "fulfilled" && (
        <OverviewCard data={collection.value} month={monthLabel} />
      )}

      {kpi.status === "fulfilled" && (
        <section>
          <h2 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">
            Today at a glance
          </h2>
          <KpiGrid data={kpi.value} />
        </section>
      )}

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
