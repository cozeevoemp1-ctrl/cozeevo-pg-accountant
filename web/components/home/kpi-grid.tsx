"use client";

import React, { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { IconTile } from "@/components/ui/icon-tile";
import { getKpiDetail, getTenantDues, cancelNoShow, quickBook, createPayment, type KpiDetailItem, type TenantDues } from "@/lib/api";
import { rupee, rupeeL } from "@/lib/format";
import type { KpiResponse } from "@/lib/api";

interface KpiGridProps {
  data: KpiResponse;
  initialDetails?: Record<string, KpiDetailItem[]>;
}

type TileKey = "occupied" | "vacant" | "checkins_today" | "checkouts_today" | "dues" | "no_show" | "notices" | null;
type RentRange = "all" | "lt12" | "12to15" | "15to20" | "gt20";
type GenderFilter = "all" | "male" | "female" | "empty";
type StayFilter = "all" | "monthly" | "daily";
type BuildingFilter = "all" | "THOR" | "HULK";

const RENT_RANGES: { value: RentRange; label: string }[] = [
  { value: "all", label: "All rents" },
  { value: "lt12", label: "< ₹12k" },
  { value: "12to15", label: "₹12k–15k" },
  { value: "15to20", label: "₹15k–20k" },
  { value: "gt20", label: "> ₹20k" },
];

const STAY_FILTERS: { value: StayFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "monthly", label: "Regular" },
  { value: "daily", label: "Day-wise" },
];

const GENDER_FILTERS: { value: GenderFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
  { value: "empty", label: "Empty" },
];

function inRentRange(rent: number | undefined, range: RentRange): boolean {
  if (range === "all" || rent === undefined) return true;
  if (range === "lt12") return rent < 12000;
  if (range === "12to15") return rent >= 12000 && rent < 15000;
  if (range === "15to20") return rent >= 15000 && rent < 20000;
  if (range === "gt20") return rent >= 20000;
  return true;
}

function matchesGender(gender: string | undefined, filter: GenderFilter): boolean {
  if (filter === "all") return true;
  if (filter === "empty") return gender === "empty";
  if (filter === "male") return gender === "male";
  if (filter === "female") return gender === "female";
  return true;
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function TenantDetailCard({ dues, onClose }: { dues: TenantDues; onClose: () => void }) {
  return (
    <div className="mt-2 rounded-tile border border-brand-pink bg-white p-4 shadow-sm">
      <div className="flex justify-between items-start mb-3">
        <div>
          <p className="text-sm font-bold text-ink">{dues.name}</p>
          <p className="text-xs text-ink-muted">Room {dues.room_number} · {dues.building_code}</p>
        </div>
        <button onClick={onClose} className="text-ink-muted text-xl leading-none px-1 -mt-0.5">×</button>
      </div>
      <div className="flex flex-col divide-y divide-[#F0EDE9]">
        {[
          { label: "Check-in", value: fmtDate(dues.checkin_date) },
          { label: "Sharing type", value: dues.sharing_type ? dues.sharing_type.charAt(0).toUpperCase() + dues.sharing_type.slice(1) : "—" },
          { label: "Agreed rent", value: rupee(dues.rent) + "/mo" },
          { label: "Security deposit", value: rupee(dues.security_deposit) },
          { label: "Maintenance", value: dues.maintenance_fee > 0 ? rupee(dues.maintenance_fee) + "/mo" : "—" },
        ].map(({ label, value }) => (
          <div key={label} className="flex justify-between py-1.5">
            <span className="text-xs text-ink-muted">{label}</span>
            <span className="text-xs font-medium text-ink">{value}</span>
          </div>
        ))}
        <div className="flex justify-between py-1.5">
          <span className="text-xs text-ink-muted">Dues this month</span>
          <span className={`text-xs font-bold ${dues.dues > 0 ? "text-status-due" : "text-status-paid"}`}>
            {dues.dues > 0 ? rupee(dues.dues) : "Paid ✓"}
          </span>
        </div>
        {dues.last_payment_date && (
          <div className="flex justify-between py-1.5">
            <span className="text-xs text-ink-muted">Last payment</span>
            <span className="text-xs font-medium text-ink">
              {rupee(dues.last_payment_amount ?? 0)} · {fmtDate(dues.last_payment_date)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

type PayMethod = "CASH" | "UPI";
const COLLECT_METHODS: { value: PayMethod; label: string }[] = [
  { value: "CASH", label: "Cash" },
  { value: "UPI", label: "UPI" },
];

function QuickCollectModal({ item, onClose, onSuccess }: {
  item: KpiDetailItem;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [rentAmt, setRentAmt] = useState(String(item.dues ?? ""));
  const [depositAmt, setDepositAmt] = useState("");
  const [rentMethod, setRentMethod] = useState<PayMethod>("CASH");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [fullDues, setFullDues] = useState<import("@/lib/api").TenantDues | null>(null);

  useEffect(() => {
    if (!item.tenancy_id) return;
    getTenantDues(item.tenancy_id).then((d) => {
      setFullDues(d);
      const depDue = Math.max(0, d.deposit_due ?? 0);
      const rentOnly = Math.max(0, d.dues ?? 0);
      if (depDue > 0) setDepositAmt(String(depDue));
      setRentAmt(String(rentOnly));
    }).catch(() => {});
  }, [item.tenancy_id]);

  function currentMonth() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!fullDues) { setError("Could not load tenant info — try again"); return; }
    const ra = parseFloat(rentAmt) || 0;
    const da = parseFloat(depositAmt) || 0;
    if (ra <= 0 && da <= 0) { setError("Enter at least one amount"); return; }
    setSaving(true); setError("");
    try {
      if (ra > 0) {
        await createPayment({ tenant_id: fullDues.tenant_id, amount: ra, method: rentMethod, for_type: "rent", period_month: currentMonth() });
      }
      if (da > 0) {
        await createPayment({ tenant_id: fullDues.tenant_id, amount: da, method: "UPI", for_type: "deposit", period_month: currentMonth() });
      }
      setSuccess(true);
      setTimeout(() => { onSuccess(); onClose(); }, 1200);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment failed");
    } finally {
      setSaving(false);
    }
  }

  const depositDue = fullDues ? Math.max(0, fullDues.deposit_due ?? 0) : 0;
  const rentDue = fullDues ? Math.max(0, fullDues.dues ?? 0) : (item.dues ?? 0);
  const totalCollect = (parseFloat(rentAmt) || 0) + (parseFloat(depositAmt) || 0);

  return (
    <div className="fixed inset-0 flex items-center justify-center px-4" style={{ zIndex: 9999 }} onClick={onClose}>
      <div className="absolute inset-0 bg-black/50" />
      <div
        className="relative w-full max-w-sm bg-surface rounded-2xl px-5 pt-5 pb-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <div>
            <p className="text-base font-extrabold text-ink">Collect payment</p>
            <p className="text-xs text-ink-muted">{item.name} · Room {item.room}</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-full bg-[#F6F5F0] flex items-center justify-center text-ink-muted font-bold text-lg leading-none">×</button>
        </div>

        {success ? (
          <div className="rounded-tile bg-[#D1FAE5] border border-[#6EE7B7] px-4 py-3 text-sm font-semibold text-[#065F46] text-center">
            Payment recorded!
          </div>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-4">
            {error && (
              <div className="rounded-tile bg-[#FFF0F0] border border-status-warn px-3 py-2 text-xs text-status-warn font-medium">{error}</div>
            )}

            {/* Rent dues field — always shown */}
            {rentDue > 0 && (
              <div>
                <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">
                  Rent dues (₹) · <span className="text-status-due">{rupee(rentDue)} outstanding</span>
                </label>
                <input
                  type="number"
                  value={rentAmt}
                  onChange={(e) => setRentAmt(e.target.value)}
                  onWheel={(e) => e.currentTarget.blur()}
                  min="0"
                  className="w-full text-lg font-bold rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink outline-none focus:ring-2 focus:ring-brand-pink"
                  autoFocus
                />
                <div className="flex gap-1.5 mt-1.5">
                  {COLLECT_METHODS.map((m) => (
                    <button key={m.value} type="button" onClick={() => setRentMethod(m.value)}
                      className={`flex-1 py-1.5 text-[10px] font-bold rounded-lg border transition-colors ${
                        rentMethod === m.value ? "bg-brand-pink text-white border-brand-pink" : "bg-[#F6F5F0] text-ink-muted border-[#E0DDD8]"
                      }`}>
                      {m.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Deposit dues field — only shown if unpaid deposit exists */}
            {depositDue > 0 && (
              <div>
                <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">
                  Deposit (₹) · <span className="text-status-due">{rupee(depositDue)} unpaid</span>
                </label>
                <input
                  type="number"
                  value={depositAmt}
                  onChange={(e) => setDepositAmt(e.target.value)}
                  onWheel={(e) => e.currentTarget.blur()}
                  min="0"
                  className="w-full text-lg font-bold rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink outline-none focus:ring-2 focus:ring-brand-pink"
                />
                <p className="text-[10px] text-[#00AEED] font-bold mt-1">Always recorded as UPI</p>
              </div>
            )}

            {/* Summary: outstanding / collecting / remaining */}
            {fullDues && (
              <div className="rounded-tile bg-[#F6F5F0] px-3 py-2.5 flex flex-col gap-1">
                {[
                  { label: "Total outstanding", value: rentDue + depositDue, muted: true },
                  { label: "Collecting now",     value: totalCollect,         muted: false },
                  { label: "Remaining after",    value: Math.max(0, (rentDue + depositDue) - totalCollect), muted: true, warn: (rentDue + depositDue) - totalCollect > 0 },
                ].map(({ label, value, muted, warn }) => (
                  <div key={label} className="flex items-center justify-between">
                    <span className="text-[11px] text-ink-muted">{label}</span>
                    <span className={`text-[11px] font-bold ${warn ? "text-status-due" : muted ? "text-ink-muted" : "text-ink"}`}>
                      {rupee(value)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <button
              type="submit"
              disabled={saving || !fullDues}
              className="w-full rounded-pill bg-brand-pink py-3 text-sm font-bold text-white active:opacity-70 disabled:opacity-50"
            >
              {saving ? "Saving…" : totalCollect > 0 ? `Collect ${rupee(totalCollect)}` : "Collect"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

interface QuickBookModalProps {
  room: string;
  onClose: () => void;
  onSuccess: () => void;
}

function QuickBookModal({ room, onClose, onSuccess }: QuickBookModalProps) {
  const [stayType, setStayType] = useState<"monthly" | "daily">("monthly");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [checkinDate, setCheckinDate] = useState("");
  const [checkoutDate, setCheckoutDate] = useState("");
  const [rent, setRent] = useState("");
  const [dailyRate, setDailyRate] = useState("");
  const [advance, setAdvance] = useState("");
  const [maintenance, setMaintenance] = useState("5000");
  const [deposit, setDeposit] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!name.trim() || !phone.trim() || !checkinDate) {
      setError("Name, phone and check-in date are required");
      return;
    }
    if (stayType === "monthly" && !rent) { setError("Monthly rent is required"); return; }
    if (stayType === "daily" && !dailyRate) { setError("Daily rate is required"); return; }
    if (stayType === "daily" && !checkoutDate) { setError("Check-out date is required"); return; }
    setSaving(true);
    try {
      const result = await quickBook(
        stayType === "daily"
          ? {
              room_number: room,
              tenant_name: name.trim(),
              tenant_phone: phone.trim(),
              checkin_date: checkinDate,
              stay_type: "daily",
              daily_rate: parseFloat(dailyRate),
              checkout_date: checkoutDate,
              security_deposit: parseFloat(deposit) || 0,
              booking_amount: parseFloat(advance) || 0,
            }
          : {
              room_number: room,
              tenant_name: name.trim(),
              tenant_phone: phone.trim(),
              checkin_date: checkinDate,
              stay_type: "monthly",
              monthly_rent: parseFloat(rent),
              maintenance_fee: parseFloat(maintenance) || 0,
              security_deposit: parseFloat(deposit) || parseFloat(rent) || 0,
              booking_amount: parseFloat(advance) || 0,
            }
      );
      setSuccess(true);
      if (!result.whatsapp_sent) {
        setError("Booked! WhatsApp message could not be sent — share the link manually.");
      } else {
        setTimeout(() => { onSuccess(); onClose(); }, 1400);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Booking failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 flex items-center justify-center px-4" style={{ zIndex: 9999 }} onClick={onClose}>
      <div className="absolute inset-0 bg-black/50" />
      <div
        className="relative w-full max-w-lg bg-surface rounded-2xl px-5 pt-5 pb-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="text-base font-extrabold text-ink">Pre-book Room {room}</p>
            <p className="text-xs text-ink-muted">Bed stays vacant until arrival</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-full bg-[#F6F5F0] flex items-center justify-center text-ink-muted font-bold text-lg leading-none">×</button>
        </div>

        {success && !error ? (
          <div className="rounded-tile bg-[#D1FAE5] border border-[#6EE7B7] px-4 py-3 text-sm font-semibold text-[#065F46] text-center">
            Booked! WhatsApp sent to customer.
          </div>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-3">
            {error && (
              <div className="rounded-tile bg-[#FFF0F0] border border-status-warn px-3 py-2 text-xs text-status-warn font-medium">
                {error}
              </div>
            )}
            {/* Stay type toggle */}
            <div className="flex rounded-lg overflow-hidden border border-[#E0DDD8]">
              {(["monthly", "daily"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setStayType(t)}
                  className={`flex-1 py-2 text-xs font-bold transition-colors ${
                    stayType === t ? "bg-brand-pink text-white" : "bg-[#F6F5F0] text-ink-muted"
                  }`}
                >
                  {t === "monthly" ? "Monthly" : "Day-wise"}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">Customer name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Full name"
                  className="w-full text-sm rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink placeholder:text-ink-muted outline-none focus:ring-2 focus:ring-brand-pink"
                  required
                />
              </div>
              <div className="col-span-2">
                <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">WhatsApp number</label>
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="10-digit mobile"
                  className="w-full text-sm rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink placeholder:text-ink-muted outline-none focus:ring-2 focus:ring-brand-pink"
                  required
                />
              </div>
              <div>
                <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">Check-in date</label>
                <input
                  type="date"
                  value={checkinDate}
                  onChange={(e) => setCheckinDate(e.target.value)}
                  className="w-full text-sm rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink outline-none focus:ring-2 focus:ring-brand-pink"
                  required
                />
              </div>
              {stayType === "daily" ? (
                <>
                  <div>
                    <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">Check-out date</label>
                    <input
                      type="date"
                      value={checkoutDate}
                      onChange={(e) => setCheckoutDate(e.target.value)}
                      className="w-full text-sm rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink outline-none focus:ring-2 focus:ring-brand-pink"
                      required
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">Daily rate (₹/night)</label>
                    <input
                      type="number"
                      value={dailyRate}
                      onChange={(e) => setDailyRate(e.target.value)}
                      placeholder="e.g. 800"
                      min="1"
                      className="w-full text-sm rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink placeholder:text-ink-muted outline-none focus:ring-2 focus:ring-brand-pink"
                      required
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">Security deposit (₹)</label>
                    <input
                      type="number"
                      value={deposit}
                      onChange={(e) => setDeposit(e.target.value)}
                      placeholder="0 if none"
                      min="0"
                      className="w-full text-sm rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink placeholder:text-ink-muted outline-none focus:ring-2 focus:ring-brand-pink"
                    />
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">Monthly rent (₹)</label>
                    <input
                      type="number"
                      value={rent}
                      onChange={(e) => { setRent(e.target.value); setDeposit(e.target.value); }}
                      placeholder="e.g. 12000"
                      min="1"
                      className="w-full text-sm rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink placeholder:text-ink-muted outline-none focus:ring-2 focus:ring-brand-pink"
                      required
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">Maintenance (₹/mo)</label>
                    <input
                      type="number"
                      value={maintenance}
                      onChange={(e) => setMaintenance(e.target.value)}
                      min="0"
                      className="w-full text-sm rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink placeholder:text-ink-muted outline-none focus:ring-2 focus:ring-brand-pink"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">Security deposit (₹)</label>
                    <input
                      type="number"
                      value={deposit}
                      onChange={(e) => setDeposit(e.target.value)}
                      placeholder="Auto = 1 month rent"
                      min="0"
                      className="w-full text-sm rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink placeholder:text-ink-muted outline-none focus:ring-2 focus:ring-brand-pink"
                    />
                  </div>
                </>
              )}
              {/* Advance — common for both stay types */}
              <div className="col-span-2">
                <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">Advance collected (₹)</label>
                <input
                  type="number"
                  value={advance}
                  onChange={(e) => setAdvance(e.target.value)}
                  placeholder="0 if none"
                  min="0"
                  className="w-full text-sm rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink placeholder:text-ink-muted outline-none focus:ring-2 focus:ring-brand-pink"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={saving}
              className="w-full rounded-pill bg-brand-pink py-3 text-sm font-bold text-white active:opacity-70 disabled:opacity-50 mt-1"
            >
              {saving ? "Booking…" : "Book & send WhatsApp link"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

interface PanelProps {
  open: TileKey;
  positionStyle: React.CSSProperties;
  // filters
  nameSearch: string; setNameSearch: (v: string) => void;
  rentRange: RentRange; setRentRange: (v: RentRange) => void;
  roomSearch: string; setRoomSearch: (v: string) => void;
  genderFilter: GenderFilter; setGenderFilter: (v: GenderFilter) => void;
  stayFilter: StayFilter; setStayFilter: (v: StayFilter) => void;
  buildingFilter: BuildingFilter; setBuildingFilter: (v: BuildingFilter) => void;
  showStaff: boolean; toggleStaff: () => void;
  noticeSortDir: "asc" | "desc"; setNoticeSortDir: (v: "asc" | "desc") => void;
  noticeMonthFilter: string; setNoticeMonthFilter: (v: string) => void;
  noticeTypeFilter: "all" | "full_room" | "premium" | "male" | "female"; setNoticeTypeFilter: (v: "all" | "full_room" | "premium" | "male" | "female") => void;
  noticeMonths: string[];
  allItems: KpiDetailItem[];
  // data
  filtered: KpiDetailItem[];
  loading: boolean;
  selected: TenantDues | null;
  detailLoading: boolean;
  selectItem: (item: KpiDetailItem) => void;
  setSelected: (v: TenantDues | null) => void;
  cancellingId: number | null;
  onCancel: (item: KpiDetailItem) => void;
  onBook: (room: string) => void;
  onCollect: (item: KpiDetailItem) => void;
}

function monthLabel(key: string): string {
  const m = parseInt(key.split("-")[1])
  return ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][m]
}

function ExpansionPanel({
  open, positionStyle,
  nameSearch, setNameSearch,
  rentRange, setRentRange,
  roomSearch, setRoomSearch,
  genderFilter, setGenderFilter,
  stayFilter, setStayFilter,
  buildingFilter, setBuildingFilter,
  showStaff, toggleStaff,
  noticeSortDir, setNoticeSortDir,
  noticeMonthFilter, setNoticeMonthFilter,
  noticeTypeFilter, setNoticeTypeFilter,
  noticeMonths,
  allItems,
  filtered, loading, selected, detailLoading, selectItem, setSelected,
  cancellingId, onCancel, onBook, onCollect,
}: PanelProps) {
  const noticeTotalBeds = allItems.reduce((s, i) => s + (i.beds_freed ?? 1), 0)
  const noticeFullRooms = (() => {
    const seen = new Set<string>()
    let n = 0
    for (const i of allItems) { if (i.is_full_exit && !seen.has(i.room)) { seen.add(i.room); n++ } }
    return n
  })()
  return (
    <div className="absolute top-full mt-1.5 z-20 rounded-tile border-2 border-brand-pink bg-surface overflow-hidden shadow-lg" style={{ ...positionStyle, animation: "panel-in 150ms ease-out" }}>

      {/* Filter bar — dues */}
      {open === "dues" && (
        <div className="px-3 pt-3 pb-2 flex flex-col gap-2">
          <input
            type="text"
            placeholder="Name or room…"
            value={nameSearch}
            onChange={(e) => { setNameSearch(e.target.value); setSelected(null); }}
            className="w-full text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
          />
          <div className="flex gap-1.5 items-center">
            {(["all", "THOR", "HULK"] as const).map((b) => (
              <button
                key={b}
                onClick={() => setBuildingFilter(b)}
                className={`text-[10px] font-semibold px-2.5 py-1 rounded-pill border transition-colors ${
                  buildingFilter === b
                    ? "bg-brand-pink text-white border-brand-pink"
                    : "bg-[#F6F5F0] text-ink-muted border-[#E0DDD8]"
                }`}
              >
                {b === "all" ? "All" : b}
              </button>
            ))}
            {!loading && filtered.length > 0 && (
              <span className="ml-auto text-[10px] font-bold text-brand-pink">
                ₹{filtered.reduce((s, it) => s + (it.dues ?? 0), 0).toLocaleString("en-IN")}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Filter bar — occupied */}
      {open === "occupied" && (
        <div className="px-3 pt-3 pb-2 flex flex-col gap-2">
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Name or room…"
              value={nameSearch}
              onChange={(e) => { setNameSearch(e.target.value); setSelected(null); }}
              className="flex-1 text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
            />
            <select
              value={rentRange}
              onChange={(e) => setRentRange(e.target.value as RentRange)}
              className="text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-2 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink"
            >
              {RENT_RANGES.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </div>
          {!loading && filtered.length > 0 && (
            <p className="text-right text-[10px] font-bold text-brand-pink">{filtered.length} tenants</p>
          )}
        </div>
      )}

      {/* Filter bar — checkins/checkouts */}
      {(open === "checkins_today" || open === "checkouts_today") && (
        <div className="px-3 pt-3 pb-2 flex flex-col gap-2">
          <input
            type="text"
            placeholder="Name or room…"
            value={nameSearch}
            onChange={(e) => { setNameSearch(e.target.value); setSelected(null); }}
            className="w-full text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
          />
          <div className="flex gap-1.5 items-center">
            {STAY_FILTERS.map((sf) => (
              <button
                key={sf.value}
                onClick={() => setStayFilter(sf.value)}
                className={`text-[10px] font-semibold px-2.5 py-1 rounded-pill border transition-colors ${
                  stayFilter === sf.value
                    ? "bg-brand-pink text-white border-brand-pink"
                    : "bg-[#F6F5F0] text-ink-muted border-[#E0DDD8]"
                }`}
              >
                {sf.label}
              </button>
            ))}
            {!loading && filtered.length > 0 && (
              <span className="ml-auto text-[10px] font-bold text-brand-pink">{filtered.length} total</span>
            )}
          </div>
        </div>
      )}

      {/* Filter bar — no_show */}
      {open === "no_show" && (
        <div className="px-3 pt-3 pb-2 flex flex-col gap-2">
          <input
            type="text"
            placeholder="Name or room…"
            value={nameSearch}
            onChange={(e) => { setNameSearch(e.target.value); setSelected(null); }}
            className="w-full text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
          />
          {!loading && filtered.length > 0 && (() => {
            const overdue = filtered.filter((it) => it.is_overdue).length;
            return (
              <div className="flex items-center justify-between">
                {overdue > 0
                  ? <span className="text-[10px] font-bold text-[#991B1B] bg-[#FEE2E2] px-2 py-0.5 rounded-pill">{overdue} overdue</span>
                  : <span />
                }
                <span className="text-[10px] font-bold text-brand-pink">{filtered.length} total</span>
              </div>
            );
          })()}
        </div>
      )}

      {/* Filter bar — notices */}
      {open === "notices" && (
        <div className="px-3 pt-3 pb-2 flex flex-col gap-2">
          {/* Summary */}
          <div className="flex gap-2 text-[10px] font-bold text-ink-muted">
            <span className="text-ink">{allItems.reduce((s, i) => s + (i.beds_freed ?? 1), 0)} beds</span>
            <span>·</span>
            <span className="text-brand-pink">{(() => { const s = new Set<string>(); let n = 0; for (const i of allItems) { if (i.is_full_exit && !s.has(i.room)) { s.add(i.room); n++ } } return n })() } full rooms</span>
            <span className="ml-auto">{filtered.length} shown</span>
          </div>
          {/* Sort + search + month chips */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setNoticeSortDir(noticeSortDir === "asc" ? "desc" : "asc")}
              className="flex-shrink-0 w-7 h-7 rounded-lg border border-[#E0DDD8] bg-[#F6F5F0] flex items-center justify-center text-[11px] font-bold text-ink-muted"
            >
              {noticeSortDir === "asc" ? "↑" : "↓"}
            </button>
            <input
              type="text"
              placeholder="Name or room…"
              value={nameSearch}
              onChange={(e) => { setNameSearch(e.target.value); setSelected(null); }}
              className="flex-1 min-w-0 text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-1.5 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
            />
            <div className="flex gap-1 flex-shrink-0">
              {["all", ...noticeMonths].map(mk => (
                <button
                  key={mk}
                  onClick={() => setNoticeMonthFilter(mk)}
                  className={`px-2 py-1 rounded-lg text-[10px] font-bold border ${noticeMonthFilter === mk ? "bg-brand-pink text-white border-brand-pink" : "bg-[#F6F5F0] text-ink-muted border-[#E0DDD8]"}`}
                >
                  {mk === "all" ? "All" : monthLabel(mk)}
                </button>
              ))}
            </div>
          </div>
          {/* Type chips */}
          <div className="flex gap-1 flex-wrap">
            {(["all", "full_room", "premium", "male", "female"] as const).map(f => {
              const labels: Record<string, string> = { all: "All", full_room: "Full room", premium: "Premium", male: "Male", female: "Female" }
              const activeColors: Record<string, string> = {
                all: "bg-brand-pink text-white border-brand-pink",
                full_room: "bg-[#FFF3E0] text-[#C25000] border-[#F5C78A]",
                premium: "bg-[#F3E8FF] text-[#7C3AED] border-[#D8B4FE]",
                male: "bg-[#EFF6FF] text-[#1D4ED8] border-[#93C5FD]",
                female: "bg-[#FDF2F8] text-[#BE185D] border-[#F9A8D4]",
              }
              return (
                <button
                  key={f}
                  onClick={() => setNoticeTypeFilter(f)}
                  className={`px-2 py-1 rounded-lg text-[10px] font-bold border ${noticeTypeFilter === f ? activeColors[f] : "bg-[#F6F5F0] text-ink-muted border-[#E0DDD8]"}`}
                >
                  {labels[f]}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Filter bar — vacant */}
      {open === "vacant" && (
        <div className="px-3 pt-3 pb-2 flex flex-col gap-2">
          <input
            type="text"
            placeholder="Search room…"
            value={roomSearch}
            onChange={(e) => setRoomSearch(e.target.value)}
            className="w-full text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
          />
          <div className="flex gap-1.5 items-center flex-wrap">
            {GENDER_FILTERS.map((gf) => (
              <button
                key={gf.value}
                onClick={() => setGenderFilter(gf.value)}
                className={`text-[10px] font-semibold px-2.5 py-1 rounded-pill border transition-colors ${
                  genderFilter === gf.value
                    ? "bg-brand-pink text-white border-brand-pink"
                    : "bg-[#F6F5F0] text-ink-muted border-[#E0DDD8]"
                }`}
              >
                {gf.label}
              </button>
            ))}
            <button
              onClick={toggleStaff}
              className={`text-[10px] font-semibold px-2.5 py-1 rounded-pill border transition-colors ${
                showStaff
                  ? "bg-[#6366F1] text-white border-[#6366F1]"
                  : "bg-[#F6F5F0] text-ink-muted border-[#E0DDD8]"
              }`}
            >
              Staff
            </button>
            {!loading && filtered.length > 0 && (() => {
              const beds = filtered.reduce((s, it) => {
                if (it.is_staff_room) return s;
                const m = it.detail.match(/^(\d+)/);
                return s + (m ? parseInt(m[1]) : 1);
              }, 0);
              return beds > 0 ? <span className="ml-auto text-[10px] font-bold text-brand-pink">{beds} beds free</span> : null;
            })()}
          </div>
        </div>
      )}

      {/* Scrollable list */}
      <div className="overflow-y-auto px-3" style={{ maxHeight: "256px" }}>
        {loading ? (
          <p className="text-xs text-ink-muted text-center py-4">Loading…</p>
        ) : filtered.length === 0 ? (
          <p className="text-xs text-ink-muted text-center py-4">No matches</p>
        ) : (
          <div className="flex flex-col divide-y divide-[#F0EDE9]">
            {filtered.map((item, i) => (
              <React.Fragment key={i}>
              <div
                className={`flex justify-between items-center py-2.5 w-full text-left rounded px-1 -mx-1 transition-colors ${
                  item.tenancy_id
                    ? "hover:bg-[#F6F5F0] active:bg-[#EEDFE8]"
                    : ""
                } ${selected?.tenancy_id === item.tenancy_id ? "bg-[#FCE2EE]" : ""}`}
              >
                <button
                  onClick={() => open === "dues" ? (item.tenancy_id ? onCollect(item) : undefined) : selectItem(item)}
                  disabled={!item.tenancy_id}
                  className={`flex-1 flex justify-between items-center text-left min-w-0 ${item.tenancy_id ? "cursor-pointer" : "cursor-default"}`}
                >
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-ink">{item.name}</p>
                    <p className="text-[10px] text-ink-muted">Room {item.room}</p>
                  </div>
                  <div className="flex items-center gap-1.5 ml-2 flex-shrink-0">
                    {open === "notices" && item.deposit_eligible !== undefined && (
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-pill ${
                        item.deposit_eligible
                          ? "bg-[#D1FAE5] text-[#065F46]"
                          : "bg-[#FEE2E2] text-[#991B1B]"
                      }`}>
                        {item.deposit_eligible ? "Refundable" : "Forfeited"}
                      </span>
                    )}
                    {open === "vacant" && item.is_staff_room && (
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded-pill bg-[#EEF2FF] text-[#4338CA]">
                        Staff
                      </span>
                    )}
                    {open === "vacant" && item.upcoming_checkin && (() => {
                      const d = new Date(item.upcoming_checkin)
                      d.setDate(d.getDate() - 1)
                      return (
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-pill bg-[#FEF3C7] text-[#92400E]">
                          Until {d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                        </span>
                      )
                    })()}
                    {open === "no_show" && item.is_overdue && (
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-[#FEE2E2] text-[#991B1B]">
                        {item.days_overdue}d late
                      </span>
                    )}
                    <p className={`text-xs font-medium ${open === "dues" ? "text-status-due font-semibold" : "text-ink-muted"}`}>{item.detail}</p>
                    {item.tenancy_id && open !== "checkouts_today" && open !== "checkins_today" && open !== "dues" && (
                      <span className="text-xs text-brand-pink font-bold">
                        {selected?.tenancy_id === item.tenancy_id ? "▾" : "›"}
                      </span>
                    )}
                  </div>
                </button>
                {open === "checkouts_today" && (
                  item.is_checked_out ? (
                    <span className="ml-2 flex-shrink-0 text-[10px] font-bold text-[#A0A0A0] bg-[#E8E8E8] px-2.5 py-1 rounded-full cursor-not-allowed">
                      Checked out
                    </span>
                  ) : (
                    <Link
                      href={item.tenancy_id ? `/checkout/new?tenancy_id=${item.tenancy_id}` : "/checkout/new"}
                      className="ml-2 flex-shrink-0 text-[10px] font-bold text-white bg-brand-pink px-2.5 py-1 rounded-full active:opacity-70"
                    >
                      Check-out →
                    </Link>
                  )
                )}
                {open === "checkins_today" && (
                  <Link
                    href={item.tenancy_id ? `/checkin/new?tenancy_id=${item.tenancy_id}` : "/checkin/new"}
                    className="ml-2 flex-shrink-0 text-[10px] font-bold text-white bg-brand-pink px-2.5 py-1 rounded-full active:opacity-70"
                  >
                    Check-in →
                  </Link>
                )}
                {open === "no_show" && item.is_overdue && item.tenancy_id && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onCancel(item); }}
                    disabled={cancellingId === item.tenancy_id}
                    className="ml-2 flex-shrink-0 text-[10px] font-bold text-white bg-[#991B1B] px-2.5 py-1 rounded-full active:opacity-70 disabled:opacity-50"
                  >
                    {cancellingId === item.tenancy_id ? "…" : "Cancel →"}
                  </button>
                )}
                {open === "dues" && item.tenancy_id && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onCollect(item); }}
                    className="ml-2 flex-shrink-0 text-[10px] font-bold text-white bg-brand-pink px-2.5 py-1 rounded-full active:opacity-70"
                  >
                    Collect →
                  </button>
                )}
                {open === "vacant" && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onBook(item.room); }}
                    className="ml-2 flex-shrink-0 text-[10px] font-bold text-white bg-brand-pink px-2.5 py-1 rounded-full active:opacity-70"
                  >
                    Book →
                  </button>
                )}
              </div>
              {/* Inline detail expand — notices tile only */}
              {open === "notices" && selected?.tenancy_id === item.tenancy_id && (
                <div className="pb-3 pt-1">
                  {detailLoading
                    ? <p className="text-xs text-center text-ink-muted py-2">Loading…</p>
                    : selected && (() => {
                        const totalDue = (selected.dues || 0) + (selected.deposit_due || 0)
                        return (
                          <div className="rounded-tile border border-[#F0EDE9] bg-[#F6F5F0] px-3 py-2.5 flex flex-col gap-2">
                            <div className="flex justify-between items-center">
                              <span className="text-xs text-ink-muted">Dues outstanding</span>
                              <span className={`text-xs font-bold ${totalDue > 0 ? "text-status-due" : "text-status-paid"}`}>
                                {totalDue > 0 ? rupee(totalDue) : "Clear ✓"}
                              </span>
                            </div>
                            {selected.deposit_due > 0 && (
                              <div className="flex justify-between items-center">
                                <span className="text-[11px] text-ink-muted">Deposit due</span>
                                <span className="text-[11px] font-semibold text-ink-muted">{rupee(selected.deposit_due)}</span>
                              </div>
                            )}
                            <div className="flex gap-2 pt-1">
                              {totalDue > 0 && (
                                <Link
                                  href={`/payment/new?tenancy_id=${selected.tenancy_id}`}
                                  className="flex-1 text-center rounded-pill bg-brand-pink py-2 text-[11px] font-bold text-white active:opacity-70"
                                >
                                  Collect ₹{totalDue.toLocaleString("en-IN")} →
                                </Link>
                              )}
                              <Link
                                href={`/checkout/new?tenancy_id=${selected.tenancy_id}`}
                                className={`${totalDue > 0 ? "" : "flex-1"} text-center rounded-pill border border-[#E2DEDD] py-2 px-3 text-[11px] font-bold text-ink active:opacity-70`}
                              >
                                Check-out →
                              </Link>
                            </div>
                          </div>
                        )
                      })()
                  }
                </div>
              )}
              </React.Fragment>
            ))}
          </div>
        )}
        {open === "checkouts_today" && (
          <div className="px-3 pb-2 pt-1">
            <Link href="/checkouts" className="block text-center text-xs font-bold text-brand-pink py-1.5 rounded-xl border border-brand-pink/30 active:opacity-70">
              View all checkouts this month →
            </Link>
          </div>
        )}
      </div>

      {/* Tenant detail card — tiles that use bottom expand (not notices, not dues) */}
      {open !== "notices" && open !== "dues" && (
        <div className="px-3 pb-3">
          {detailLoading && (
            <p className="text-xs text-ink-muted text-center pt-2">Loading details…</p>
          )}
          {selected && !detailLoading && (
            <TenantDetailCard dues={selected} onClose={() => setSelected(null)} />
          )}
        </div>
      )}
    </div>
  );
}

export function KpiGrid({ data, initialDetails }: KpiGridProps) {
  const [open, setOpen] = useState<TileKey>(null);
  const [items, setItems] = useState<KpiDetailItem[]>([]);
  const [loading, setLoading] = useState(false);

  const [nameSearch, setNameSearch] = useState("");
  const [rentRange, setRentRange] = useState<RentRange>("all");
  const [roomSearch, setRoomSearch] = useState("");
  const [genderFilter, setGenderFilter] = useState<GenderFilter>("all");
  const [stayFilter, setStayFilter] = useState<StayFilter>("all");
  const [buildingFilter, setBuildingFilter] = useState<BuildingFilter>("all");
  const [showStaff, setShowStaff] = useState(false);
  const [noticeSortDir, setNoticeSortDir] = useState<"asc" | "desc">("asc");
  const [noticeMonthFilter, setNoticeMonthFilter] = useState<string>("all");
  const [noticeTypeFilter, setNoticeTypeFilter] = useState<"all" | "full_room" | "premium" | "male" | "female">("all");

  const [selected, setSelected] = useState<TenantDues | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [cancellingId, setCancellingId] = useState<number | null>(null);
  const [bookingRoom, setBookingRoom] = useState<string | null>(null);
  const [collectingItem, setCollectingItem] = useState<KpiDetailItem | null>(null);

  const cache = useRef<Map<string, KpiDetailItem[]>>(
    new Map(Object.entries(initialDetails ?? {}))
  );
  const inflight = useRef<Set<string>>(new Set());

  // Warm cache on mount — only for tiles that will actually render
  useEffect(() => {
    const keys: TileKey[] = ["occupied", "vacant", "dues"];
    if (data.checkins_today > 0 || data.checkouts_today > 0) keys.push("checkins_today", "checkouts_today");
    if (data.no_show_count > 0) keys.push("no_show");
    if (data.notices_count > 0) keys.push("notices");
    keys.forEach((k) => prefetch(k));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Close panel on page scroll — prevents the fixed backdrop from blocking scroll
  // after the user scrolls away from the KPI section
  const openRef = useRef(open);
  openRef.current = open;
  useEffect(() => {
    function onScroll() { if (openRef.current) { setOpen(null); resetFilters(); } }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function prefetch(key: TileKey) {
    if (!key || cache.current.has(key) || inflight.current.has(key)) return;
    inflight.current.add(key);
    try {
      const res = await getKpiDetail(key);
      cache.current.set(key, res.items);
    } catch { /* ignore */ }
    inflight.current.delete(key);
  }

  function close() {
    setOpen(null);
    resetFilters();
  }

  async function toggle(key: TileKey) {
    if (open === key) { close(); return; }
    setOpen(key);
    resetFilters();
    if (cache.current.has(key!)) {
      setItems(cache.current.get(key!)!);
      return;
    }
    setLoading(true);
    try {
      const res = await getKpiDetail(key!);
      cache.current.set(key!, res.items);
      setItems(res.items);
    } catch { setItems([]); }
    setLoading(false);
  }

  function resetFilters() {
    setNameSearch("");
    setRentRange("all");
    setRoomSearch("");
    setGenderFilter("all");
    setStayFilter("all");
    setBuildingFilter("all");
    setShowStaff(false);
    setNoticeSortDir("asc");
    setNoticeMonthFilter("all");
    setNoticeTypeFilter("all");
    setSelected(null);
  }

  async function toggleStaff() {
    const next = !showStaff;
    setShowStaff(next);
    const cacheKey = next ? "vacant_staff" : "vacant";
    if (cache.current.has(cacheKey)) {
      setItems(cache.current.get(cacheKey)!);
      return;
    }
    setLoading(true);
    try {
      const res = await getKpiDetail("vacant", { includeStaff: next });
      cache.current.set(cacheKey, res.items);
      setItems(res.items);
    } catch { setItems([]); }
    setLoading(false);
  }

  async function selectItem(item: KpiDetailItem) {
    if (!item.tenancy_id) return;
    if (selected?.tenancy_id === item.tenancy_id) { setSelected(null); return; }
    setDetailLoading(true);
    try {
      const dues = await getTenantDues(item.tenancy_id);
      setSelected(dues);
    } catch { /* ignore */ }
    setDetailLoading(false);
  }

  async function onCancel(item: KpiDetailItem) {
    if (!item.tenancy_id) return;
    if (!confirm(`Cancel booking for ${item.name} (Room ${item.room})? This cannot be undone.`)) return;
    setCancellingId(item.tenancy_id);
    try {
      await cancelNoShow(item.tenancy_id);
      // Refresh no_show list
      cache.current.delete("no_show");
      const res = await getKpiDetail("no_show");
      cache.current.set("no_show", res.items);
      setItems(res.items);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Cancel failed");
    }
    setCancellingId(null);
  }

  const filtered: KpiDetailItem[] = (() => {
    if (open === "notices") {
      const q = nameSearch.trim().toLowerCase();
      return [...items]
        .filter(it => {
          if (noticeMonthFilter !== "all" && it.expected_checkout_iso?.slice(0, 7) !== noticeMonthFilter) return false;
          if (noticeTypeFilter === "full_room" && !it.is_full_exit) return false;
          if (noticeTypeFilter === "premium" && it.sharing_type !== "premium") return false;
          if (noticeTypeFilter === "male" && it.gender !== "male") return false;
          if (noticeTypeFilter === "female" && it.gender !== "female") return false;
          if (q && !it.name.toLowerCase().includes(q) && !it.room.toLowerCase().includes(q)) return false;
          return true;
        })
        .sort((a, b) => {
          const diff = (a.days_remaining ?? 9999) - (b.days_remaining ?? 9999);
          return noticeSortDir === "asc" ? diff : -diff;
        });
    }
    return items.filter((it) => {
      if (open === "dues") {
        const matchName =
          !nameSearch.trim() ||
          it.name.toLowerCase().includes(nameSearch.toLowerCase()) ||
          it.room.toLowerCase().includes(nameSearch.toLowerCase());
        const matchBuilding = buildingFilter === "all" || it.building === buildingFilter;
        return matchName && matchBuilding;
      }
      if (open === "occupied") {
        const matchName =
          !nameSearch.trim() ||
          it.name.toLowerCase().includes(nameSearch.toLowerCase()) ||
          it.room.toLowerCase().includes(nameSearch.toLowerCase());
        return matchName && inRentRange(it.rent, rentRange);
      }
      if (open === "checkins_today" || open === "checkouts_today") {
        const matchName =
          !nameSearch.trim() ||
          it.name.toLowerCase().includes(nameSearch.toLowerCase()) ||
          it.room.toLowerCase().includes(nameSearch.toLowerCase());
        const matchStay = stayFilter === "all" || it.stay_type === stayFilter;
        return matchName && matchStay;
      }
      if (open === "no_show") {
        return (
          !nameSearch.trim() ||
          it.name.toLowerCase().includes(nameSearch.toLowerCase()) ||
          it.room.toLowerCase().includes(nameSearch.toLowerCase())
        );
      }
      if (open === "vacant") {
        const matchRoom =
          !roomSearch.trim() ||
          it.room.toLowerCase().includes(roomSearch.toLowerCase());
        if (showStaff) return matchRoom && it.is_staff_room === true;
        const matchGender = matchesGender(it.gender, genderFilter);
        return matchRoom && matchGender;
      }
      return true;
    });
  })();

  const noticeMonths = [...new Set(items.map(i => i.expected_checkout_iso?.slice(0, 7) ?? "").filter(Boolean))].sort();

  // Shared props for ExpansionPanel
  const panelProps = {
    open,
    nameSearch, setNameSearch,
    rentRange, setRentRange,
    roomSearch, setRoomSearch,
    genderFilter, setGenderFilter,
    stayFilter, setStayFilter,
    buildingFilter, setBuildingFilter,
    showStaff, toggleStaff,
    noticeSortDir, setNoticeSortDir,
    noticeMonthFilter, setNoticeMonthFilter: (v: string) => setNoticeMonthFilter(v),
    noticeTypeFilter, setNoticeTypeFilter,
    noticeMonths,
    allItems: items,
    filtered, loading, selected, detailLoading, selectItem, setSelected,
    cancellingId, onCancel,
    onBook: (room: string) => { close(); setBookingRoom(room); },
    onCollect: (item: KpiDetailItem) => { setCollectingItem(item); },
  };

  const leftStyle: React.CSSProperties = { left: 0, width: "calc(200% + 0.75rem)" };
  const rightStyle: React.CSSProperties = { right: 0, width: "calc(200% + 0.75rem)" };
  const fullStyle: React.CSSProperties = { left: 0, right: 0 };

  return (
    <>
    <div className="grid grid-cols-2 gap-3">
      {/* Backdrop — catches outside taps to close the panel */}
      {open && <div className="fixed inset-0 z-10" onClick={close} />}

      {/* Occupied beds — left col */}
      <div className="relative">
        <IconTile
          icon="🏠" label="Occupied beds"
          value={`${data.occupied_beds} / ${data.total_beds}`}
          color="blue" active={open === "occupied"}
          onClick={() => toggle("occupied")}
        />
        {open === "occupied" && (
          <ExpansionPanel {...panelProps} positionStyle={leftStyle} />
        )}
      </div>

      {/* Vacant beds — right col */}
      <div className="relative">
        <IconTile
          icon="🪟" label="Vacant beds"
          value={data.vacant_beds}
          color="green" active={open === "vacant"}
          onClick={() => toggle("vacant")}
        />
        {open === "vacant" && (
          <ExpansionPanel {...panelProps} positionStyle={rightStyle} />
        )}
      </div>

      {/* Active tenants — no expansion */}
      <IconTile
        icon="👥" label="Active tenants"
        value={data.active_tenants}
        color="pink"
      />

      {/* Dues pending — right col */}
      <div className="relative">
        <IconTile
          icon="💸" label={`Dues pending · ${data.overdue_tenants}`}
          value={rupeeL(data.overdue_amount)}
          color={data.overdue_tenants > 0 ? "orange" : "green"}
          active={open === "dues"}
          onClick={() => toggle("dues")}
        />
        {open === "dues" && (
          <ExpansionPanel {...panelProps} positionStyle={rightStyle} />
        )}
      </div>

      {/* Check-ins / Check-outs — conditional */}
      {(data.checkins_today > 0 || data.checkouts_today > 0) && (
        <>
          <div className="relative">
            <IconTile
              icon="↗️" label="Check-ins today"
              value={data.checkins_today}
              color="green" active={open === "checkins_today"}
              onClick={() => toggle("checkins_today")}
            />
            {open === "checkins_today" && (
              <ExpansionPanel {...panelProps} positionStyle={leftStyle} />
            )}
          </div>
          <div className="relative">
            <IconTile
              icon="↙️" label="Check-outs today"
              value={data.checkouts_today}
              color="orange" active={open === "checkouts_today"}
              onClick={() => toggle("checkouts_today")}
            />
            {open === "checkouts_today" && (
              <ExpansionPanel {...panelProps} positionStyle={rightStyle} />
            )}
          </div>
        </>
      )}

      {/* Awaiting check-in — full width */}
      {data.no_show_count > 0 && (
        <div className="col-span-2 relative">
          <IconTile
            icon="⏳" label="Awaiting check-in"
            value={data.no_show_count}
            color="orange" active={open === "no_show"}
            onClick={() => toggle("no_show")}
          />
          {open === "no_show" && (
            <ExpansionPanel {...panelProps} positionStyle={fullStyle} />
          )}
        </div>
      )}

      {/* On notice — full width */}
      {data.notices_count > 0 && (
        <div className="col-span-2 relative">
          <IconTile
            icon="📋" label={`On notice · ${data.notices_count}`}
            value={`${data.notices_count} leaving`}
            color="orange" active={open === "notices"}
            onClick={() => toggle("notices")}
          />
          {open === "notices" && (
            <ExpansionPanel {...panelProps} positionStyle={fullStyle} />
          )}
        </div>
      )}

    </div>

    {bookingRoom && (
      <QuickBookModal
        room={bookingRoom}
        onClose={() => setBookingRoom(null)}
        onSuccess={() => { cache.current.delete("vacant"); toggle("vacant"); }}
      />
    )}
    {collectingItem && (
      <QuickCollectModal
        item={collectingItem}
        onClose={() => setCollectingItem(null)}
        onSuccess={() => { cache.current.delete("dues"); toggle("dues"); }}
      />
    )}
    </>
  );
}
