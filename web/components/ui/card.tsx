import { clsx } from "clsx";
import type { HTMLAttributes } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "flat";
}

export function Card({ className, variant = "default", ...props }: CardProps) {
  return (
    <div
      className={clsx(
        "rounded-card bg-surface",
        variant === "default" && "shadow-sm",
        className,
      )}
      {...props}
    />
  );
}
