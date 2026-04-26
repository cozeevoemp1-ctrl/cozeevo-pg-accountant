import { clsx } from "clsx";
import type { ButtonHTMLAttributes } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md" | "lg";
}

export function Button({
  className,
  variant = "primary",
  size = "md",
  ...props
}: ButtonProps) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center font-semibold rounded-pill transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
        {
          "bg-brand-pink text-white hover:opacity-90 active:opacity-80": variant === "primary",
          "bg-surface border border-[#E2DEDD] text-ink hover:bg-bg": variant === "secondary",
          "bg-transparent text-ink-muted hover:text-ink": variant === "ghost",
        },
        {
          "text-xs px-3 py-1.5": size === "sm",
          "text-sm px-5 py-2.5": size === "md",
          "text-base px-6 py-3": size === "lg",
        },
        className,
      )}
      {...props}
    />
  );
}
