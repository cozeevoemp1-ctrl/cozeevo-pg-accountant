"use client";

import { useState } from "react";
import { IconTile } from "@/components/ui/icon-tile";
import { getKpiDetail, getTenantDues, type KpiDetailItem, type TenantDues } from "@/lib/api";
import { rupee } from "@/lib/format";
import type { KpiResponse } from "@/lib/api";

interface KpiGridProps {
  data: KpiResponse;
}

type TileKey = "occupied" | "vacant" | "checkins_today" | "checkouts_today" | null;

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
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<TenantDues | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  async function toggle(key: TileKey) {
    if (open === key) { setOpen(null); setSearch(""); setSelected(null); return; }
    setOpen(key);
    setSearch("");
    setSelected(null);
    setLoading(true);
    try {
      const res = await getKpiDetail(key!);
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

  const filtered = search.trim()
    ? items.filter(
        (it) =>
          it.name.toLowerCase().includes(search.toLowerCase()) ||
          it.room.toLowerCase().includes(search.toLowerCase())
      )
    : items;

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
          icon="⚠️" label="Open complaints"
          value={data.open_complaints}
          color={data.open_complaints > 0 ? "orange" : "green"}
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

      {/* Expandable panel */}
      {open && (
        <div className="mt-2 rounded-tile border-2 border-brand-pink bg-surface overflow-hidden">
          {/* Search */}
          <div className="px-3 pt-3 pb-2">
            <input
              type="text"
              placeholder="Search name or room…"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setSelected(null); }}
              className="w-full text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
            />
          </div>

          {/* Fixed-height scrollable list */}
          <div className="overflow-y-auto px-3" style={{ maxHeight: "256px" }}>
            {loading ? (
              <p className="text-xs text-ink-muted text-center py-4">Loading…</p>
            ) : filtered.length === 0 ? (
              <p className="text-xs text-ink-muted text-center py-4">
                {search ? "No matches" : "No records found"}
              </p>
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
                      <p className="text-xs font-medium text-ink-muted">{item.detail}</p>
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
