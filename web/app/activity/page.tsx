import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth-server";
import { getActivityFeed, type ActivityFeedEvent } from "@/lib/api";
import Link from "next/link";

const TYPE_CONFIG: Record<ActivityFeedEvent["type"], { icon: string; color: string }> = {
  payment:     { icon: "₹", color: "bg-[#D1FAE5] text-[#065F46]" },
  checkin:     { icon: "→", color: "bg-[#DBEAFE] text-[#1D4ED8]" },
  checkout:    { icon: "←", color: "bg-[#FEF3C7] text-[#92400E]" },
  rent_change: { icon: "↑", color: "bg-[#EDE9FE] text-[#5B21B6]" },
  room_change: { icon: "⇄", color: "bg-[#FCE7F3] text-[#9D174D]" },
  void:        { icon: "✕", color: "bg-[#FEE2E2] text-[#991B1B]" },
  adjustment:  { icon: "~", color: "bg-[#FEF3C7] text-[#78350F]" },
  notice:      { icon: "!", color: "bg-[#FEF3C7] text-[#B45309]" },
  other:       { icon: "•", color: "bg-[#F6F5F0] text-ink-muted" },
};

function _dayLabel(ts: string): string {
  const d = new Date(ts);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const day   = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff  = Math.round((today.getTime() - day.getTime()) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7)  return d.toLocaleDateString("en-IN", { weekday: "long" });
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function _timeLabel(ts: string): string {
  return new Date(ts).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
}

function _dayKey(ts: string): string {
  const d = new Date(ts);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

export default async function ActivityPage() {
  const session = await getSession();
  if (!session) redirect("/login");

  const token = session.session.access_token;
  let events: ActivityFeedEvent[] = [];
  let error = false;
  try {
    const data = await getActivityFeed(80, token);
    events = data.events;
  } catch {
    error = true;
  }

  // Group by day
  const groups: { key: string; label: string; events: ActivityFeedEvent[] }[] = [];
  for (const ev of events) {
    const key = _dayKey(ev.ts);
    const last = groups[groups.length - 1];
    if (last && last.key === key) {
      last.events.push(ev);
    } else {
      groups.push({ key, label: _dayLabel(ev.ts), events: [ev] });
    }
  }

  return (
    <main className="min-h-screen bg-bg">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 pt-12 pb-4 bg-surface border-b border-[#F0EDE9]">
        <Link href="/"
          className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold flex-shrink-0"
          aria-label="Back">←</Link>
        <div className="flex-1">
          <p className="text-xs text-ink-muted font-medium">Cozeevo</p>
          <h1 className="text-lg font-extrabold text-ink leading-tight">Activity</h1>
        </div>
      </div>

      <div className="px-4 pt-4 pb-32 max-w-lg mx-auto flex flex-col gap-4">
        {error ? (
          <p className="text-sm text-ink-muted text-center mt-12">Unable to load activity</p>
        ) : events.length === 0 ? (
          <p className="text-sm text-ink-muted text-center mt-12">No activity yet</p>
        ) : (
          groups.map((group) => (
            <section key={group.key}>
              <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">{group.label}</p>
              <div className="bg-surface rounded-card border border-[#F0EDE9] divide-y divide-[#F0EDE9]">
                {group.events.map((ev) => {
                  const cfg = TYPE_CONFIG[ev.type] ?? TYPE_CONFIG.other;
                  return (
                    <div key={ev.id} className="flex items-start gap-3 px-4 py-3">
                      <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5 ${cfg.color}`}>
                        {cfg.icon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-ink leading-snug">{ev.label}</p>
                        {ev.sublabel && (
                          <p className="text-xs text-ink-muted mt-0.5 truncate">{ev.sublabel}</p>
                        )}
                      </div>
                      <p className="text-[10px] text-ink-muted flex-shrink-0 mt-0.5">{_timeLabel(ev.ts)}</p>
                    </div>
                  );
                })}
              </div>
            </section>
          ))
        )}
      </div>
    </main>
  );
}
