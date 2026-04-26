import { IconTile } from "@/components/ui/icon-tile";
import type { KpiResponse } from "@/lib/api";

interface KpiGridProps {
  data: KpiResponse;
}

export function KpiGrid({ data }: KpiGridProps) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <IconTile
        icon="🏠"
        label="Occupied beds"
        value={`${data.occupied_beds} / ${data.total_beds}`}
        color="blue"
      />
      <IconTile
        icon="🪟"
        label="Vacant beds"
        value={data.vacant_beds}
        color="green"
      />
      <IconTile
        icon="👥"
        label="Active tenants"
        value={data.active_tenants}
        color="pink"
      />
      <IconTile
        icon="⚠️"
        label="Open complaints"
        value={data.open_complaints}
        color={data.open_complaints > 0 ? "orange" : "green"}
      />
      {(data.checkins_today > 0 || data.checkouts_today > 0) && (
        <>
          <IconTile icon="↗️" label="Check-ins today" value={data.checkins_today} color="green" />
          <IconTile icon="↙️" label="Check-outs today" value={data.checkouts_today} color="orange" />
        </>
      )}
    </div>
  );
}
