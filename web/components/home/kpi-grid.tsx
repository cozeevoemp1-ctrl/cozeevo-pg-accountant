"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { IconTile } from "@/components/ui/icon-tile";
import { getKpiDetail, getTenantDues, cancelNoShow, quickBook, type KpiDetailItem, type TenantDues } from "@/lib/api";
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

interface QuickBookModalProps {
  room: string;
  onClose: () => void;
  onSuccess: () => void;
}

function QuickBookModal({ room, onClose, onSuccess }: QuickBookModalProps) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [checkinDate, setCheckinDate] = useState("");
  const [rent, setRent] = useState("");
  const [maintenance, setMaintenance] = useState("5000");
  const [deposit, setDeposit] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!name.trim() || !phone.trim() || !checkinDate || !rent) {
      setError("All fields are required");
      return;
    }
    setSaving(true);
    try {
      const result = await quickBook({
        room_number: room,
        tenant_name: name.trim(),
        tenant_phone: phone.trim(),
        checkin_date: checkinDate,
        monthly_rent: parseFloat(rent),
        maintenance_fee: parseFloat(maintenance) || 0,
        security_deposit: parseFloat(deposit) || parseFloat(rent) || 0,
      });
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
  filtered, loading, selected, detailLoading, selectItem, setSelected,
  cancellingId, onCancel, onBook,
}: PanelProps) {
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
          <input
            type="text"
            placeholder="Name or room…"
            value={nameSearch}
            onChange={(e) => { setNameSearch(e.target.value); setSelected(null); }}
            className="w-full text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
          />
          {!loading && filtered.length > 0 && (
            <p className="text-right text-[10px] font-bold text-brand-pink">{filtered.length} total</p>
          )}
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
                const m = it.detail.match(/^(\d+)/);
                return s + (m ? parseInt(m[1]) : 1);
              }, 0);
              return <span className="ml-auto text-[10px] font-bold text-brand-pink">{beds} beds free</span>;
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
              <div
                key={i}
                className={`flex justify-between items-center py-2.5 w-full text-left rounded px-1 -mx-1 transition-colors ${
                  item.tenancy_id
                    ? "hover:bg-[#F6F5F0] active:bg-[#EEDFE8]"
                    : ""
                } ${selected?.tenancy_id === item.tenancy_id ? "bg-[#FCE2EE]" : ""}`}
              >
                <button
                  onClick={() => selectItem(item)}
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
                    {item.tenancy_id && open !== "checkouts_today" && open !== "checkins_today" && (
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
                {open === "vacant" && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onBook(item.room); }}
                    className="ml-2 flex-shrink-0 text-[10px] font-bold text-white bg-brand-pink px-2.5 py-1 rounded-full active:opacity-70"
                  >
                    Book →
                  </button>
                )}
              </div>
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

      {/* Tenant detail card */}
      <div className="px-3 pb-3">
        {detailLoading && (
          <p className="text-xs text-ink-muted text-center pt-2">Loading details…</p>
        )}
        {selected && !detailLoading && (
          <TenantDetailCard dues={selected} onClose={() => setSelected(null)} />
        )}
      </div>
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

  const [selected, setSelected] = useState<TenantDues | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [cancellingId, setCancellingId] = useState<number | null>(null);
  const [bookingRoom, setBookingRoom] = useState<string | null>(null);

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

  const filtered = items.filter((it) => {
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
    if (open === "no_show" || open === "notices") {
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
      const matchGender = matchesGender(it.gender, genderFilter);
      return matchRoom && matchGender;
    }
    return true;
  });

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
    filtered, loading, selected, detailLoading, selectItem, setSelected,
    cancellingId, onCancel,
    onBook: (room: string) => { close(); setBookingRoom(room); },
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
    </>
  );
}
