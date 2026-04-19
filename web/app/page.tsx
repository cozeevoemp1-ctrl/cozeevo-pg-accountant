import { rupee } from "@/lib/format";

export default function Home() {
  return (
    <main className="flex flex-col items-center justify-center min-h-screen p-6">
      <div className="text-center">
        <div className="inline-flex items-center justify-center w-20 h-20 rounded-[22px] bg-brand-pink text-white text-4xl font-extrabold shadow-lg">
          K
        </div>
        <h1 className="text-3xl font-extrabold mt-6 tracking-tight">Kozzy</h1>
        <p className="text-ink-muted mt-2">Cozeevo Help Desk</p>
        <p className="text-xs text-ink-muted mt-8">
          PWA scaffold · {rupee(240000)}
        </p>
      </div>
    </main>
  );
}
