import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth-server";
import { getActivityFeed, type ActivityFeedEvent } from "@/lib/api";
import Link from "next/link";
import { LogoutAvatar } from "@/components/home/logout-avatar";
import { ActivityFeed } from "@/components/activity/activity-feed";

export default async function ActivityPage() {
  const session = await getSession();
  if (!session) redirect("/login");

  const token = session.session.access_token;
  const userName = (session.user.user_metadata?.name as string | undefined) ?? session.user.email ?? "U";
  const userInitial = userName[0].toUpperCase();
  let events: ActivityFeedEvent[] = [];
  let error = false;
  try {
    const data = await getActivityFeed(120, token);
    events = data.events;
  } catch {
    error = true;
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
        <LogoutAvatar initial={userInitial} />
      </div>

      <div className="px-4 pt-4 pb-32 max-w-lg mx-auto">
        {error ? (
          <p className="text-sm text-ink-muted text-center mt-12">Unable to load activity</p>
        ) : (
          <ActivityFeed events={events} />
        )}
      </div>
    </main>
  );
}
