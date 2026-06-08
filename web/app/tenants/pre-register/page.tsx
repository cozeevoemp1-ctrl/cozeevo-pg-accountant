"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { quickBook, checkRoomAvailability, type RoomCheckResult } from "@/lib/api";
import { Card } from "@/components/ui/card";
import Link from "next/link";
import { DatePickerInput } from "@/components/ui/date-picker-input";

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export default function PreRegisterPage() {
  const router = useRouter();
  const [name, setName]             = useState("");
  const [phone, setPhone]           = useState("");
  const [checkinDate, setCheckinDate] = useState("");
  const [rent, setRent]             = useState("");
  const [maintenance, setMaintenance] = useState("5000");
  const [deposit, setDeposit]       = useState("");
  const [advance, setAdvance]       = useState("");
  const [advanceMode, setAdvanceMode] = useState<"cash" | "upi">("upi");
  const [notes, setNotes]           = useState("");
  const [bedType, setBedType]       = useState<"regular" | "premium">("regular");
  const [depositOverridden, setDepositOverridden] = useState(false);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState("");
  const [done, setDone]             = useState<{ form_url: string; whatsapp_sent: boolean } | null>(null);

  // Room pre-assignment
  const [roomInput, setRoomInput]   = useState("");
  const [roomInfo, setRoomInfo]     = useState<RoomCheckResult | null>(null);
  const [roomChecking, setRoomChecking] = useState(false);
  const [roomError, setRoomError]   = useState("");
  const roomTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const rentNum = parseFloat(rent) || 0;
  const depositDisplay = depositOverridden ? deposit : rent;
  const depositNum = parseFloat(depositDisplay) || rentNum || undefined;

  function handleDepositChange(e: React.ChangeEvent<HTMLInputElement>) {
    setDeposit(e.target.value);
    setDepositOverridden(true);
  }

  function handleDepositBlur() {
    if (deposit === "") setDepositOverridden(false);
  }

  async function checkRoom(roomNum: string, date: string) {
    if (!roomNum.trim()) { setRoomInfo(null); setRoomError(""); return; }
    setRoomChecking(true);
    setRoomError("");
    try {
      const result = await checkRoomAvailability(roomNum.trim().toUpperCase(), date || undefined);
      setRoomInfo(result);
    } catch (err: unknown) {
      setRoomInfo(null);
      if (err instanceof Error && err.message.includes("404")) {
        setRoomError("Room not found");
      } else if (err instanceof Error && err.message.includes("staff")) {
        setRoomError("Staff room — cannot pre-book");
      } else {
        setRoomError("Could not check room");
      }
    }
    setRoomChecking(false);
  }

  function handleRoomChange(val: string) {
    setRoomInput(val);
    setRoomInfo(null);
    setRoomError("");
    if (roomTimerRef.current) clearTimeout(roomTimerRef.current);
    roomTimerRef.current = setTimeout(() => checkRoom(val, checkinDate), 600);
  }

  useEffect(() => {
    if (roomInput.trim()) checkRoom(roomInput, checkinDate);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkinDate]);

  // Derive room status label
  function getRoomStatus() {
    if (!roomInput.trim() || !roomInfo) return null;
    if (checkinDate && roomInfo.beds_free_on_date !== undefined) {
      if (roomInfo.beds_free_on_date > 0) {
        return { ok: true, msg: `Available — ${roomInfo.beds_free_on_date} bed${roomInfo.beds_free_on_date > 1 ? "s" : ""} free on your check-in date` };
      }
      const freeFrom = roomInfo.earliest_free_date ? fmtDate(roomInfo.earliest_free_date) : null;
      const tenantNames = (roomInfo.current_tenants || []).map(t => t.name).join(", ");
      return {
        ok: false,
        msg: freeFrom
          ? `Room occupied by ${tenantNames || "current tenant"}${roomInfo.current_tenants?.[0]?.checkout_date ? ` (leaving ${fmtDate(roomInfo.current_tenants[0].checkout_date)})` : ""}. Free from ${freeFrom} — set check-in on or after that date.`
          : `Room is fully booked with no checkout dates set.`,
      };
    }
    if (roomInfo.free_beds > 0) {
      return { ok: true, msg: `${roomInfo.free_beds} bed${roomInfo.free_beds > 1 ? "s" : ""} free right now` };
    }
    const tenants = (roomInfo.current_tenants || roomInfo.occupants || []);
    const names = tenants.map((t: { name: string }) => t.name).join(", ");
    return { ok: false, msg: `Room is occupied${names ? ` (${names})` : ""}. Enter a check-in date after they check out.` };
  }

  const roomStatus = getRoomStatus();
  const targetRoom = roomInput.trim().toUpperCase() || "000";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!name.trim())    { setError("Name is required"); return; }
    if (!phone.trim())   { setError("Phone is required"); return; }
    if (!checkinDate)    { setError("Expected move-in date is required"); return; }
    if (!roomInput.trim()) { setError("Room number is required. Select a specific room."); return; }
    if (roomStatus && !roomStatus.ok) {
      setError("Room is not available for the selected check-in date — fix the room or date first.");
      return;
    }

    setLoading(true);
    try {
      const result = await quickBook({
        room_number:      roomInput.trim().toUpperCase(),
        tenant_name:      name.trim(),
        tenant_phone:     phone.trim(),
        checkin_date:     checkinDate,
        stay_type:        "monthly",
        monthly_rent:     rentNum || 1,
        maintenance_fee:  parseFloat(maintenance) || 5000,
        security_deposit: depositNum,
        booking_amount:   parseFloat(advance) || 0,
        advance_mode:     advanceMode,
        sharing_type:     bedType === "premium" ? "premium" : "",
        notes:            notes.trim() || undefined,
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
          <p className="text-xs text-ink-muted">
            Pre-booked into Room {roomInput.trim().toUpperCase()}. Approve check-in when they arrive.
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
          Pre-register a confirmed tenant. You can assign a specific room (even if occupied, as long as the current tenant has a checkout date before the new check-in date) or leave it blank to assign later.
        </p>
        <form onSubmit={submit} className="flex flex-col gap-4">

          <div>
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Customer name *</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Full name"
              className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 h-[42px] text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">WhatsApp number *</label>
            <input
              type="tel"
              value={phone}
              onChange={e => setPhone(e.target.value)}
              placeholder="10-digit mobile"
              className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 h-[42px] text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Check-in date *</label>
              <DatePickerInput value={checkinDate} onChange={setCheckinDate} />
            </div>
            <div>
              <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Room (optional)</label>
              <input
                type="text"
                value={roomInput}
                onChange={e => handleRoomChange(e.target.value)}
                placeholder="e.g. 207"
                className={`mt-1 w-full rounded-lg border bg-surface px-3 h-[42px] text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink ${
                  roomStatus ? (roomStatus.ok ? "border-[#6EE7B7]" : "border-status-warn") : "border-[#E0DDD8]"
                }`}
              />
              {roomChecking && <p className="mt-0.5 text-[10px] text-ink-muted">Checking…</p>}
              {roomError && <p className="mt-0.5 text-[10px] text-status-due font-medium">{roomError}</p>}
              {roomStatus && (
                <p className={`mt-0.5 text-[10px] font-medium leading-snug ${roomStatus.ok ? "text-[#15803D]" : "text-status-warn"}`}>
                  {roomStatus.msg}
                </p>
              )}
              {!roomInput.trim() && <p className="mt-0.5 text-[10px] text-ink-muted">Leave blank → TBD (Room 000)</p>}
            </div>
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
              className="mt-1 w-full h-[42px] rounded-lg border border-[#E0DDD8] bg-surface px-3 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
            />
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
                className="mt-1 w-full h-[42px] rounded-lg border border-[#E0DDD8] bg-surface px-3 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Security deposit (₹)</label>
              <input
                type="number"
                value={depositDisplay}
                onChange={handleDepositChange}
                onBlur={handleDepositBlur}
                onWheel={e => e.currentTarget.blur()}
                placeholder="Auto = 1 month rent"
                min="0"
                className="mt-1 w-full h-[42px] rounded-lg border border-[#E0DDD8] bg-surface px-3 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
              />
              {rentNum > 0 && !depositOverridden && (
                <p className="mt-0.5 text-[10px] text-ink-muted">auto = 1 month rent</p>
              )}
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
              className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 h-[42px] text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
            />
            <div className="mt-2 flex rounded-lg overflow-hidden border border-[#E0DDD8] h-[42px]">
              {(["cash", "upi"] as const).map(m => (
                <button key={m} type="button"
                  onClick={() => setAdvanceMode(m)}
                  className={`flex-1 text-sm font-bold transition-colors ${advanceMode === m ? "bg-brand-pink text-white" : "bg-surface text-ink-muted"}`}>
                  {m === "cash" ? "Cash" : "UPI"}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Bed type</label>
            <div className="mt-1 flex rounded-lg overflow-hidden border border-[#E0DDD8]">
              <button
                type="button"
                onClick={() => setBedType("regular")}
                className={`flex-1 py-2.5 text-sm font-bold transition-colors ${bedType === "regular" ? "bg-brand-pink text-white" : "bg-surface text-ink-muted"}`}
              >
                Regular
              </button>
              <button
                type="button"
                onClick={() => setBedType("premium")}
                className={`flex-1 py-2.5 text-sm font-bold transition-colors ${bedType === "premium" ? "bg-brand-pink text-white" : "bg-surface text-ink-muted"}`}
              >
                Premium
              </button>
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Notes</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="e.g. referred by Kiran, needs AC room, twin-share preferred…"
              rows={2}
              className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink resize-none"
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
