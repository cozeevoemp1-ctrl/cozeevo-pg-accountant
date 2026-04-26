import type { AuthSession } from "@/lib/auth";

interface GreetingProps {
  session: AuthSession;
}

function _hour(): number {
  return new Date().getHours();
}

export function Greeting({ session }: GreetingProps) {
  const h = _hour();
  const salutation = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  const name = session.user.user_metadata?.name as string | undefined;
  const display = name ?? session.phone.slice(-4);

  return (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-xs text-ink-muted font-medium">{salutation}</p>
        <h1 className="text-xl font-extrabold text-ink leading-tight">{display}</h1>
      </div>
      <div className="w-10 h-10 rounded-full bg-brand-pink flex items-center justify-center text-white font-bold text-sm">
        {(name?.[0] ?? display[0] ?? "K").toUpperCase()}
      </div>
    </div>
  );
}
