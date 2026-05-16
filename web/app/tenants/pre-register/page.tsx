"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { quickBook } from "@/lib/api";
import { Card } from "@/components/ui/card";
import Link from "next/link";

export default function PreRegisterPage() {
  const router = useRouter();
  const [name, setName]             = useState("");
  const [phone, setPhone]           = useState("");
  const [checkinDate, setCheckinDate] = useState("");
  const [rent, setRent]             = useState("");
  const [maintenance, setMaintenance] = useState("5000");
  const [deposit, setDeposit]       = useState("");
  const [advance, setAdvance]       = useState("");
  const [depositOverridden, setDepositOverridden] = useState(false);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState("");
  const [done, setDone]             = useState<{ form_url: string; whatsapp_sent: boolean } | null>(null);

  const rentNum = parseFloat(rent) || 0;
  // deposit field mirrors rent unless user has manually overridden it
  const depositDisplay = depositOverridden ? deposit : rent;
  const depositNum = parseFloat(depositDisplay) || rentNum || undefined;

  function handleDepositChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value;
    if (val === "") {
      setDepositOverridden(false);
      setDeposit("");
    } else {
      setDepositOverridden(true);
      setDeposit(val);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!name.trim())    { setError("Name is required"); return; }
    if (!phone.trim())   { setError("Phone is required"); return; }
    if (!checkinDate)    { setError("Expected move-in date is required"); return; }

    setLoading(true);
    try {
      const result = await quickBook({
        room_number:      "000",
        tenant_name:      name.trim(),
        tenant_phone:     phone.trim(),
        checkin_date:     checkinDate,
        stay_type:        "monthly",
        monthly_rent:     rentNum || 1,
        maintenance_fee:  parseFloat(maintenance) || 5000,
        security_deposit: depositNum,
        booking_amount:   parseFloat(advance) || 0,
      });
      setDone(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to pre-register");
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
          <p className="text-xs text-ink-muted">Appears in Bookings as pending. Assign a room when they check in.</p>
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
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Customer name *</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Full name"
              className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">WhatsApp number *</label>
            <input
              type="tel"
              value={phone}
              onChange={e => setPhone(e.target.value)}
              placeholder="10-digit mobile"
              className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Check-in date *</label>
              <input
                type="date"
                value={checkinDate}
                onChange={e => setCheckinDate(e.target.value)}
                className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2.5 text-sm text-ink focus:outline-none focus:border-brand-pink"
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Monthly rent (₹)</label>
              <input
                type="number"
                value={rent}
                onChange={e => setRent(e.target.value)}
                onWheel={e => e.currentTarget.blur()}
                placeholder="e.g. 12000"
                min="0"
                className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Maintenance (₹/mo)</label>
              <input
                type="number"
                value={maintenance}
                onChange={e => setMaintenance(e.target.value)}
                onWheel={e => e.currentTarget.blur()}
                min="0"
                className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">
                Security deposit (₹)
                {rentNum > 0 && !depositOverridden && (
                  <span className="ml-1 normal-case font-normal text-ink-muted">(auto)</span>
                )}
              </label>
              <input
                type="number"
                value={depositDisplay}
                onChange={handleDepositChange}
                onWheel={e => e.currentTarget.blur()}
                placeholder="Auto = 1 month rent"
                min="0"
                className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Advance collected (₹)</label>
            <input
              type="number"
              value={advance}
              onChange={e => setAdvance(e.target.value)}
              onWheel={e => e.currentTarget.blur()}
              placeholder="0 if none"
              min="0"
              className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
            />
          </div>

          {error && <p className="text-xs text-status-due font-medium">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-xl bg-brand-pink text-white text-sm font-bold disabled:opacity-50 active:opacity-80"
          >
            {loading ? "Registering…" : "Book & send WhatsApp link"}
          </button>
        </form>
      </Card>
    </main>
  );
}
