"use client";

import { useState } from "react";
import { IconTile } from "@/components/ui/icon-tile";
import { getKpiDetail, getTenantDues, type KpiDetailItem, type TenantDues } from "@/lib/api";
import { rupee, rupeeL } from "@/lib/format";
import type { KpiResponse } from "@/lib/api";

interface KpiGridProps {
  data: KpiResponse;
}

type TileKey = "occupied" | "vacant" | "checkins_today" | "checkouts_today" | "dues" | null;
type RentRange = "all" | "lt12" | "12to15" | "15to20" | "gt20";
type GenderFilter = "all" | "male" | "female" | "empty";
type StayFilter = "all" | "monthly" | "daily";

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

export function KpiGrid({ data }: KpiGridProps) {
  const [open, setOpen] = useState<TileKey>(null);
  const [items, setItems] = useState<KpiDetailItem[]>([]);
  const [loading, setLoading] = useState(false);

  // Occupied filters
  const [nameSearch, setNameSearch] = useState("");
  const [rentRange, setRentRange] = useState<RentRange>("all");

  // Vacant filters
  const [roomSearch, setRoomSearch] = useState("");
  const [genderFilter, setGenderFilter] = useState<GenderFilter>("all");

  // Check-in/checkout filters
  const [stayFilter, setStayFilter] = useState<StayFilter>("all");

  // Dues filters
  type BuildingFilter = "all" | "THOR" | "HULK";
  const [buildingFilter, setBuildingFilter] = useState<BuildingFilter>("all");

  // Tenant detail
  const [selected, setSelected] = useState<TenantDues | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  async function toggle(key: TileKey) {
    if (open === key) {
      setOpen(null);
      resetFilters();
      return;
    }
    setOpen(key);
    resetFilters();
    setLoading(true);
    try {
      const res = await getKpiDetail(key!);
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
    setSelected(null);
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

  // Apply filters based on open tile
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
    if (open === "vacant") {
      const matchRoom =
        !roomSearch.trim() ||
        it.room.toLowerCase().includes(roomSearch.toLowerCase());
      const matchGender = matchesGender(it.gender, genderFilter);
      return matchRoom && matchGender;
    }
    return true;
  });

  return (
    <div className="flex flex-col gap-0">
      <div className="grid grid-cols-2 gap-3">
        <IconTile
          icon="🏠" label="Occupied beds"
          value={`${data.occupied_beds} / ${data.total_beds}`}
          color="blue" active={open === "occupied"}
          onClick={() => toggle("occupied")}
        />
        <IconTile
          icon="🪟" label="Vacant beds"
          value={data.vacant_beds}
          color="green" active={open === "vacant"}
          onClick={() => toggle("vacant")}
        />
        <IconTile
          icon="👥" label="Active tenants"
          value={data.active_tenants}
          color="pink"
        />
        <IconTile
          icon="💸" label={`Dues pending · ${data.overdue_tenants}`}
          value={rupeeL(data.overdue_amount)}
          color={data.overdue_tenants > 0 ? "orange" : "green"}
          active={open === "dues"}
          onClick={() => toggle("dues")}
        />
        {(data.checkins_today > 0 || data.checkouts_today > 0) && (
          <>
            <IconTile
              icon="↗️" label="Check-ins today"
              value={data.checkins_today}
              color="green" active={open === "checkins_today"}
              onClick={() => toggle("checkins_today")}
            />
            <IconTile
              icon="↙️" label="Check-outs today"
              value={data.checkouts_today}
              color="orange" active={open === "checkouts_today"}
              onClick={() => toggle("checkouts_today")}
            />
          </>
        )}
      </div>

      {open && (
        <div className="mt-2 rounded-tile border-2 border-brand-pink bg-surface overflow-hidden">

          {/* Filter bar — dues: name search + building pills */}
          {open === "dues" && (
            <div className="px-3 pt-3 pb-2 flex flex-col gap-2">
              <input
                type="text"
                placeholder="Name or room…"
                value={nameSearch}
                onChange={(e) => { setNameSearch(e.target.value); setSelected(null); }}
                className="w-full text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
              />
              <div className="flex gap-1.5">
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
              </div>
            </div>
          )}

          {/* Filter bar — occupied: name search + rent range */}
          {open === "occupied" && (
            <div className="px-3 pt-3 pb-2 flex gap-2">
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
          )}

          {/* Filter bar — checkins/checkouts: name search + stay type pills */}
          {(open === "checkins_today" || open === "checkouts_today") && (
            <div className="px-3 pt-3 pb-2 flex flex-col gap-2">
              <input
                type="text"
                placeholder="Name or room…"
                value={nameSearch}
                onChange={(e) => { setNameSearch(e.target.value); setSelected(null); }}
                className="w-full text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
              />
              <div className="flex gap-1.5">
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
              </div>
            </div>
          )}

          {/* Filter bar — vacant: room search + gender filter pills */}
          {open === "vacant" && (
            <div className="px-3 pt-3 pb-2 flex flex-col gap-2">
              <input
                type="text"
                placeholder="Search room…"
                value={roomSearch}
                onChange={(e) => setRoomSearch(e.target.value)}
                className="w-full text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
              />
              <div className="flex gap-1.5">
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
                  <button
                    key={i}
                    onClick={() => selectItem(item)}
                    disabled={!item.tenancy_id}
                    className={`flex justify-between items-center py-2.5 w-full text-left rounded px-1 -mx-1 transition-colors ${
                      item.tenancy_id
                        ? "hover:bg-[#F6F5F0] active:bg-[#EEDFE8] cursor-pointer"
                        : "cursor-default"
                    } ${selected?.tenancy_id === item.tenancy_id ? "bg-[#FCE2EE]" : ""}`}
                  >
                    <div>
                      <p className="text-xs font-semibold text-ink">{item.name}</p>
                      <p className="text-[10px] text-ink-muted">Room {item.room}</p>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <p className={`text-xs font-medium ${open === "dues" ? "text-status-due font-semibold" : "text-ink-muted"}`}>{item.detail}</p>
                      {item.tenancy_id && (
                        <span className="text-xs text-brand-pink font-bold">
                          {selected?.tenancy_id === item.tenancy_id ? "▾" : "›"}
                        </span>
                      )}
                    </div>
                  </button>
                ))}
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
      )}
    </div>
  );
}
