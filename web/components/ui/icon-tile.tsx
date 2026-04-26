import { clsx } from "clsx";
import type { ReactNode } from "react";

interface IconTileProps {
  icon: ReactNode;
  label: string;
  value: string | number;
  color?: "green" | "pink" | "blue" | "orange";
  className?: string;
}

const COLOR_MAP = {
  green: "bg-tile-green text-[#1C6B3A]",
  pink: "bg-tile-pink text-[#B91C6D]",
  blue: "bg-tile-blue text-[#0077B6]",
  orange: "bg-tile-orange text-[#9A4100]",
};

export function IconTile({
  icon,
  label,
  value,
  color = "blue",
  className,
}: IconTileProps) {
  return (
    <div
      className={clsx(
        "flex flex-col gap-1.5 rounded-tile p-3",
        COLOR_MAP[color],
        className,
      )}
    >
      <div className="text-xl">{icon}</div>
      <div className="text-xs font-medium opacity-70">{label}</div>
      <div className="text-lg font-bold leading-tight">{value}</div>
    </div>
  );
}
