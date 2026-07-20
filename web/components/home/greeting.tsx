import type { AuthSession } from "@/lib/auth";
import { LogoutAvatar } from "./logout-avatar";

interface GreetingProps {
  session: AuthSession;
}

const IS_DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "1";

function _hour(): number {
  return new Date().getHours();
}

const MORNING_MSGS = ["Ready to crush today?", "Let's make it count!", "Good numbers start early."]
const AFTERNOON_MSGS = ["How's the day looking?", "Keep the momentum going!", "Halfway through — strong!"]
const EVENING_MSGS = ["Great work today.", "Almost done for the day!", "Wrap it up strong."]

export function Greeting({ session }: GreetingProps) {
  const h = _hour();
  const salutation = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  const msgs = h < 12 ? MORNING_MSGS : h < 17 ? AFTERNOON_MSGS : EVENING_MSGS;
  const tagline = msgs[new Date().getDate() % msgs.length];

  const name = session.user.user_metadata?.name as string | undefined;
  const emailName = session.user.email?.split("@")[0];
  const display = name ?? emailName ?? session.phone.slice(-4);

  return (
    <div className="flex items-center justify-between">
      <div>
        <div className="flex items-center gap-2">
          <p className="text-xs text-ink-muted font-medium">{salutation} · {tagline}</p>
          {IS_DEMO && (
            <span className="text-[10px] font-bold uppercase tracking-wide text-amber-800 bg-amber-100 border border-amber-300 rounded-full px-2 py-0.5 leading-none">
              Demo
            </span>
          )}
        </div>
        <h1 className="text-xl font-extrabold text-ink leading-tight capitalize">{display}</h1>
      </div>
      <LogoutAvatar initial={(name?.[0] ?? display[0] ?? "K").toUpperCase()} />
    </div>
  );
}
