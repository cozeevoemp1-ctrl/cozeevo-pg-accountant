"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { quickBook } from "@/lib/api";
import { Card } from "@/components/ui/card";
import Link from "next/link";

export default function PreRegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [checkinDate, setCheckinDate] = useState("");
  const [rent, setRent] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<{ form_url: string; whatsapp_sent: boolean } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!name.trim()) { setError("Name is required"); return; }
    if (!phone.trim()) { setError("Phone is required"); return; }
    if (!checkinDate) { setError("Expected move-in date is required"); return; }

    setLoading(true);
    try {
      const result = await quickBook({
        room_number: "000",
        tenant_name: name.trim(),
        tenant_phone: phone.trim(),
        checkin_date: checkinDate,
        stay_type: "monthly",
        monthly_rent: rent ? parseFloat(rent) : 1,
        security_deposit: 0,
      });
      setDone(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to pre-register";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  if (done) {
    return (
      <main className="flex flex-col gap-4 px-4 pt-6 pb-24 max-w-lg mx-auto">
        <div className="flex items-center gap-3">
          <Link href="/" className="w-9 h-9 rounded-full bg-[#F0EDE9] flex items-center justify-center text-ink-muted flex-shrink-0">←</Link>
          <h1 className="text-lg font-extrabold text-ink">Pre-registered</h1>
        </div>
        <Card className="p-5 flex flex-col gap-3">
          <p className="text-sm font-semibold text-status-paid">Tenant pre-registered successfully</p>
          <p className="text-sm text-ink-muted">
            {done.whatsapp_sent
              ? "WhatsApp sent with onboarding link."
              : "WhatsApp could not be sent — share the link manually."}
          </p>
          {!done.whatsapp_sent && (
            <p className="text-xs font-mono break-all text-ink">{done.form_url}</p>
          )}
          <p className="text-xs text-ink-muted">
            Appears in Bookings as pending. Assign a room when they check in.
          </p>
          <div className="flex gap-2 mt-2">
            <Link href="/onboarding/bookings" className="flex-1 text-center text-sm font-semibold text-brand-pink py-2 border border-brand-pink rounded-lg">
              View Bookings
            </Link>
            <Link href="/" className="flex-1 text-center text-sm font-semibold text-ink py-2 bg-[#F0EDE9] rounded-lg">
              Home
            </Link>
          </div>
        </Card>
      </main>
    );
  }

  return (
    <main className="flex flex-col gap-4 px-4 pt-6 pb-24 max-w-lg mx-auto">
      <div className="flex items-center gap-3">
        <Link href="/" className="w-9 h-9 rounded-full bg-[#F0EDE9] flex items-center justify-center text-ink-muted flex-shrink-0">←</Link>
        <div>
          <p className="text-xs text-ink-muted font-medium">Future tenant</p>
          <h1 className="text-lg font-extrabold text-ink leading-tight">Pre-register</h1>
        </div>
      </div>

      <Card className="p-5">
        <p className="text-xs text-ink-muted mb-4 leading-relaxed">
          Use this for tenants who confirmed joining but have no room yet. They go into Bookings (Room 000) until you assign them a room on check-in day.
        </p>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div>
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Name *</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Full name"
              className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Phone *</label>
            <input
              type="tel"
              value={phone}
              onChange={e => setPhone(e.target.value)}
              placeholder="10-digit mobile number"
              className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Expected move-in date *</label>
            <input
              type="date"
              value={checkinDate}
              onChange={e => setCheckinDate(e.target.value)}
              className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2.5 text-sm text-ink focus:outline-none focus:border-brand-pink"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Monthly rent (optional)</label>
            <input
              type="number"
              value={rent}
              onChange={e => setRent(e.target.value)}
              placeholder="e.g. 8000"
              min="0"
              className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
            />
            <p className="text-[10px] text-ink-muted mt-1">Can be set when assigning a room later</p>
          </div>

          {error && <p className="text-xs text-status-due font-medium">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-xl bg-brand-pink text-white text-sm font-bold disabled:opacity-50 active:opacity-80"
          >
            {loading ? "Registering…" : "Pre-register tenant"}
          </button>
        </form>
      </Card>
    </main>
  );
}
