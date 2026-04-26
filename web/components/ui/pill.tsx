import { clsx } from "clsx";
import type { HTMLAttributes } from "react";

type PillVariant = "default" | "paid" | "due" | "warn";

interface PillProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: PillVariant;
}

const VARIANT_CLASSES: Record<PillVariant, string> = {
  default: "bg-bg text-ink-muted border border-[#E2DEDD]",
  paid: "bg-[#DCFCE7] text-status-paid",
  due: "bg-tile-pink text-status-due",
  warn: "bg-tile-orange text-status-warn",
};

export function Pill({ variant = "default", className, ...props }: PillProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold",
        VARIANT_CLASSES[variant],
        className,
      )}
      {...props}
    />
  );
}
