import type { AuthSession } from "@/lib/auth";

interface GreetingProps {
  session: AuthSession;
}

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
        <p className="text-xs text-ink-muted font-medium">{salutation} · {tagline}</p>
        <h1 className="text-xl font-extrabold text-ink leading-tight capitalize">{display}</h1>
      </div>
      <div className="w-10 h-10 rounded-full bg-brand-pink flex items-center justify-center text-white font-bold text-sm">
        {(name?.[0] ?? display[0] ?? "K").toUpperCase()}
      </div>
    </div>
  );
}
